"""取り下げ：取り出した原稿の絞り込みと書き換え、確認ファイル。"""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from hitomane_agent import config, takedown
from hitomane_agent.checks import Manuscript
from tests.samples import row, table

BRANCH = {"code": "B001", "name": "CB株式会社"}


def exported(*rows):
    return Manuscript("取り出し", table(*rows))


class TestDates(unittest.TestCase):
    def test_two_years_ago(self):
        self.assertEqual(takedown.two_years_ago(date(2026, 11, 16)), date(2024, 11, 16))
        self.assertEqual(takedown.two_years_ago(date(2028, 2, 29)), date(2026, 2, 28))

    def test_parse_day(self):
        self.assertEqual(takedown.parse_day("2026/1/7"), date(2026, 1, 7))
        with self.assertRaises(ValueError):
            takedown.parse_day("2026-01-07")


class TestRewrite(unittest.TestCase):
    def setUp(self):
        self.cond = takedown.Conditions(date(2026, 10, 1), date(2026, 10, 31))

    def rewrite(self, *rows):
        return takedown.rewrite(exported(*rows), self.cond, BRANCH, date(2026, 11, 16))

    def test_rewrites_three_columns_only(self):
        src = row(**{"拠点": "CB株式会社", "開始日": "2026/10/05", "終了日": "2027/10/05"})
        res = self.rewrite(src)
        self.assertEqual(len(res.manuscript.rows), 1)
        out = res.manuscript.rows[0]
        self.assertEqual((out["開始日"], out["終了日"], out["ステータス"]), ("2024/11/16", "2024/11/16", "非掲載"))
        for k, v in src.items():
            if k not in ("開始日", "終了日", "ステータス"):
                self.assertEqual(out[k], v, k)

    def test_keeps_only_matching_rows(self):
        ok = row(**{"募集番号": "a", "拠点": "CB株式会社", "開始日": "2026/10/31"})
        res = self.rewrite(
            ok,
            row(**{"募集番号": "b", "拠点": "CB株式会社", "開始日": "2026/11/01"}),     # 期間の外
            row(**{"募集番号": "c", "拠点": "CB株式会社", "開始日": "2026/10/10", "ステータス": "非掲載"}),
            row(**{"募集番号": "d", "拠点": "ほかの会社", "開始日": "2026/10/10"}),    # 拠点名が違う
            row(**{"募集番号": "e", "拠点": "CB株式会社", "拠点コード": "B002", "開始日": "2026/10/10"}),
        )
        self.assertEqual([r["募集番号"] for r in res.manuscript.rows], ["a"])
        self.assertEqual(res.skipped, {"期間の外": 1, "掲載でない": 1, "拠点が違う": 2})

    def test_header_must_be_new_format(self):
        t = table(row())
        t[0][3] = "状態"
        with self.assertRaises(ValueError):
            takedown.rewrite(Manuscript("x", t), self.cond, BRANCH, date(2026, 11, 16))


class TestPrepared(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        for name, value in (("OUTPUT_DIR", d / "output"), ("STATE_DIR", d / "state")):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.cond = takedown.Conditions(date(2026, 10, 1), date(2026, 10, 31))

    def test_save_and_find_same_day_only(self):
        f = config.OUTPUT_DIR / "x.csv"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"a")
        takedown.save_prepared("Minami", self.cond, {"rows": 3, "files": [str(f)]}, date(2026, 11, 16))
        self.assertEqual(takedown.find_prepared("Minami", self.cond, date(2026, 11, 16))["rows"], 3)
        self.assertIsNone(takedown.find_prepared("Minami", self.cond, date(2026, 11, 17)))  # 次の日は使わない
        self.assertIsNone(takedown.find_prepared("other", self.cond, date(2026, 11, 16)))
        other = takedown.Conditions(date(2026, 10, 1), date(2026, 10, 30))
        self.assertIsNone(takedown.find_prepared("Minami", other, date(2026, 11, 16)))

    def test_missing_file_is_not_used(self):
        takedown.save_prepared("Minami", self.cond, {"rows": 3, "files": ["nothing.csv"]}, date(2026, 11, 16))
        self.assertIsNone(takedown.find_prepared("Minami", self.cond, date(2026, 11, 16)))


class TestPickBranch(unittest.TestCase):
    BRANCHES = [{"code": "Mat001", "name": "GritMate株式会社"}, {"code": "AA001", "name": "無し"},
                {"code": "ng001", "name": "非公開"}]

    def ms(self, *codes):
        return Manuscript("x", table(*[row(**{"募集番号": f"n{i}", "拠点コード": c}) for i, c in enumerate(codes)]))

    def test_branch_of_jobs(self):
        self.assertEqual(takedown.pick_branch(self.ms("Mat001", "Mat001"), self.BRANCHES),
                         {"code": "Mat001", "name": "GritMate株式会社"})

    def test_two_branches_stop(self):
        with self.assertRaisesRegex(RuntimeError, "Mat001 1件、ng001 1件"):
            takedown.pick_branch(self.ms("Mat001", "ng001"), self.BRANCHES)

    def test_unknown_branch_stops(self):
        with self.assertRaisesRegex(RuntimeError, "B001 が、この会社の拠点の一覧"):
            takedown.pick_branch(self.ms("B001"), self.BRANCHES)


if __name__ == "__main__":
    unittest.main()
