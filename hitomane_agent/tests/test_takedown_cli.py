"""takedown コマンド（にせの管理画面で、取り出し → 書き換え → 取り込みまで通しで）。"""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

from hitomane_agent import __main__ as cli
from hitomane_agent import config, takedown
from hitomane_agent.csv_export import read_csv
from tests import fake_hitomane
from tests.samples import row


def job(code, start, status="掲載"):
    return row(**{"募集番号": code, "開始日": start, "ステータス": status, "拠点": "CB株式会社"})


class TestTakedownCli(unittest.TestCase):
    def setUp(self):
        self.srv, self.st, url = fake_hitomane.start()
        self.addCleanup(self.srv.shutdown)
        self.st.jobs = [job("a", "2026/10/01"), job("b", "2026/10/31"), job("c", "2026/11/01"),
                        job("d", "2026/10/15", "非掲載")]
        d = Path(tempfile.mkdtemp())
        settings = config.load("settings.json")
        settings["hitomane"].update({"timeout_ms": 20000, "poll_interval_ms": 10, "export_poll_times": 5,
                                     "import_poll_times": 5})
        real_load = config.load
        patches = [
            mock.patch.object(config, "OUTPUT_DIR", d / "output"),
            mock.patch.object(config, "STATE_DIR", d / "state"),
            mock.patch.object(config, "load", side_effect=lambda n: settings if n == "settings.json" else real_load(n)),
            mock.patch("hitomane_agent.accounts.login_info",
                       lambda s, book=None, company=None: {"login_id": "Minami", "password": "pw", "url": url,
                                                           "company": "canal benefits株式会社", "code": "m66w"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv, answer=None):
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch("builtins.input", return_value=answer or "n"):
            code = cli.main(["takedown", "--from", "2026/10/01", "--to", "2026/10/31", *argv])
        return code, buf.getvalue()

    def test_prepare_only_does_not_import(self):
        code, out = self.run_cli("--prepare-only")
        self.assertEqual(code, 0, out)
        self.assertIn("取り下げる原稿: 2件", out)
        self.assertEqual(self.st.export_reserved, 1)
        self.assertEqual(self.st.imports, [])

    def test_takedown_uses_prepared_file(self):
        self.run_cli("--prepare-only")
        code, out = self.run_cli("--yes")
        self.assertEqual(code, 0, out)
        self.assertIn("確認だけ", out)
        self.assertEqual(self.st.export_reserved, 1)  # 取り出しは省いた
        self.assertEqual(len(self.st.imports), 1)
        ms = read_csv(self.st.imports[0]["file"], "x")
        new = f"{takedown.two_years_ago(date.today()):%Y/%m/%d}"
        self.assertEqual([(r["募集番号"], r["開始日"], r["終了日"], r["ステータス"]) for r in ms.rows],
                         [("a", new, new, "非掲載"), ("b", new, new, "非掲載")])
        self.assertIn("取り下げました", out)
        self.assertTrue((config.STATE_DIR / "takedown.json").exists())

    def test_takedown_without_prepare_exports_first(self):
        code, out = self.run_cli("--yes")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.st.export_reserved, 1)
        self.assertEqual(len(self.st.imports), 1)

    def test_asks_before_import(self):
        code, out = self.run_cli(answer="n")
        self.assertEqual(code, 1)
        self.assertIn("中止しました", out)
        self.assertEqual(self.st.imports, [])

    def test_zero_hits(self):
        self.st.jobs = [job("c", "2026/11/01")]
        code, out = self.run_cli("--yes")
        self.assertEqual(code, 0)
        self.assertIn("取り下げるものはありません", out)
        self.assertEqual((self.st.export_reserved, self.st.imports), (0, []))

    def test_bad_dates(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["takedown", "--from", "2026/10/31", "--to", "2026/10/01", "--yes"])
        self.assertEqual(code, 1)
        self.assertEqual(self.st.export_reserved, 0)


    def test_login_reads_and_saves_total(self):
        from hitomane_agent import workflow
        self.st.total = 49990
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["login", "--company", "m66w"])
        self.assertEqual(code, 0, buf.getvalue())
        self.assertIn("ログインできました", buf.getvalue())
        self.assertIn("49,990件", buf.getvalue())
        self.assertIn("あと 10件", buf.getvalue())
        self.assertEqual(workflow.last_total("m66w")["total"], 49990)
        self.assertIn("拠点: CB株式会社（B001）", buf.getvalue())
        self.assertEqual((self.st.export_reserved, self.st.imports), (0, []))


if __name__ == "__main__":
    unittest.main()
