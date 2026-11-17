"""取り下げのための取り出し（にせの管理画面で）。"""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from hitomane_agent.csv_export import read_csv
from hitomane_agent.exporter import HitomaneExporter
from hitomane_agent.takedown import Conditions
from tests import fake_hitomane
from tests.samples import row

OPTS = {"timeout_ms": 20000, "poll_interval_ms": 10, "export_poll_times": 5}


def job(code, start, status="掲載"):
    return row(**{"募集番号": code, "開始日": start, "ステータス": status, "拠点": "CB株式会社"})


class TestExporter(unittest.TestCase):
    def setUp(self):
        self.srv, self.st, url = fake_hitomane.start()
        self.addCleanup(self.srv.shutdown)
        self.st.jobs = [job("a", "2026/10/01"), job("b", "2026/10/31"), job("c", "2026/11/01"),
                        job("d", "2026/10/15", "非掲載")]
        self.info = {"login_id": "Minami", "password": "pw", "url": url}
        self.out = Path(tempfile.mkdtemp())
        self.ex = HitomaneExporter(self.info, OPTS, self.out, log=lambda *a: None)
        self.cond = Conditions(date(2026, 10, 1), date(2026, 10, 31))

    def test_branches(self):
        self.st.branches.append(("x", "B002", "-", "別の拠点"))  # 拠点がいくつあっても止めない
        self.assertEqual(self.ex.branches(), [{"code": "B001", "name": "CB株式会社"}, {"code": "B002", "name": "別の拠点"}])

    def test_export_by_conditions(self):
        res = self.ex.export(self.cond, self.out / "取り出し.csv")
        self.assertEqual(self.st.last_filter, (date(2026, 10, 1), date(2026, 10, 31), True))
        self.assertEqual(res["count"], 2)
        self.assertEqual(res["branches"], [{"code": "B001", "name": "CB株式会社"}])
        ms = read_csv(Path(res["file"]).read_bytes(), "x")
        self.assertEqual([r["募集番号"] for r in ms.rows], ["a", "b"])
        self.assertFalse(self.st.import_reserved)

    def test_zero_hits_does_not_export(self):
        res = self.ex.export(Conditions(date(2025, 1, 1), date(2025, 1, 31)), self.out / "取り出し.csv")
        self.assertEqual(res["count"], 0)
        self.assertIsNone(res["file"])
        self.assertEqual(self.st.export_reserved, 0)

    def test_export_timeout(self):
        self.st.export_ready_after = -1
        with self.assertRaises(RuntimeError) as e:
            self.ex.export(self.cond, self.out / "取り出し.csv")
        self.assertIn("完了しませんでした", str(e.exception))


if __name__ == "__main__":
    unittest.main()
