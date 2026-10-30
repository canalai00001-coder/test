"""入稿予定表からの実行（schedule）を確かめる。スプレッドシート・GAS・Q-mate には接続しない。"""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from qmate_agent import __main__ as cli
from qmate_agent import config
from qmate_agent import schedule as sc

RULES = config.load("rules.json")
TODAY = date(2026, 10, 30)
PLAN = [
    ["実行日", "会社", "職種", "夜勤有無", "原稿数", "", "", "原稿数", "41000"],
    ["", "AspiRove株式会社", "1クルマ", "TRUE", "500"],
    ["2026/10/30", "AspiRove株式会社", "8梱包", "FALSE", "1,000"],
    ["10/31", "AspiRove株式会社", "5半導体", "FALSE", "200"],
    ["", "", "", "FALSE", "", "", "半導体(夜勤あり/なし)", "10000"],
]


class TestPlan(unittest.TestCase):
    def test_read_plan(self):
        rows = sc.read_plan(PLAN, TODAY)
        self.assertEqual([(p.row, p.run_date, p.category, p.night, p.count) for p in rows], [
            (2, None, "1クルマ", True, 500),
            (3, date(2026, 10, 30), "8梱包", False, 1000),
            (4, date(2026, 10, 31), "5半導体", False, 200),
        ])

    def test_salary_pattern_from_floor(self):
        self.assertEqual(sc.salary_pattern("1クルマ", True, RULES, "基本"), "35万")
        self.assertEqual(sc.salary_pattern("8梱包", False, RULES, "基本"), "28万")
        self.assertEqual(sc.salary_pattern("2工場", True, RULES, "基本"), "基本")

    def test_config_row(self):
        defaults = config.load("settings.json")["schedule_defaults"]
        plan = sc.read_plan(PLAN, TODAY)[0]
        row = dict(zip(sc.CONFIG_FIELDS, sc.config_row(plan, defaults, RULES, TODAY, "0900", "下書き", 5)))
        self.assertEqual(row["グループ番号"], "予定2_0900-1")
        self.assertEqual((row["作成日"], row["職種番号"], row["会社名"], row["原稿数"]), ("2026/10/30", "1クルマ", "AspiRove株式会社", 5))
        self.assertEqual((row["ステータス"], row["夜勤の有無"], row["給与パターン"]), ("下書き", "夜勤あり", "35万"))
        self.assertEqual(len(row), 16)

    def test_heavy_light_need_title_choice(self):
        with self.assertRaises(ValueError):
            sc.config_row(sc.PlanRow(2, None, "A社", "6重め", True, 5), {}, RULES, TODAY, "0900")

    def test_output_sheets(self):
        self.assertEqual(sc.output_sheets("✅完了(2026-10-30 09:01) 500件 → 出力_A, 出力_B"), ["出力_A", "出力_B"])
        self.assertEqual(sc.output_sheets("❌エラー: 会社名が空です"), [])


class FakeBook:
    def __init__(self, status):
        self.status, self.appended, self.results = status, [], {}

    def plan_table(self):
        return PLAN

    def append_config_row(self, values):
        self.appended.append(values)
        return 5

    def config_status(self, row):
        return self.status

    def write_plan_result(self, row, text):
        self.results[row] = text


class TestScheduleCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(config, "STATE_DIR", self.tmp / "state"),
                        mock.patch.dict("os.environ", {"QMATE_GAS_TOKEN": "t"})]
        for p in self.patches:
            p.start()
        load = config.load
        self.patches.append(mock.patch.object(cli.config, "load", lambda n: dict(
            load(n), gas_webapp_url="https://script.google.com/x/exec") if n == "settings.json" else load(n)))
        self.patches[-1].start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def run_schedule(self, book, check=0, upload=0, **kw):
        args = SimpleNamespace(date="2026-10-30", row=None, status=None, count=None, dry_run=False,
                               headed=False, force=False, yes=True)
        vars(args).update(kw)
        with mock.patch.object(cli, "_spreadsheet", return_value=book), \
                mock.patch.object(sc, "GasRunner") as gas, \
                mock.patch.object(cli, "cmd_check", return_value=check) as c, \
                mock.patch.object(cli, "cmd_upload", return_value=upload) as u, \
                mock.patch("builtins.print"):
            code = cli.cmd_schedule(args)
        return code, gas, c, u

    def test_todays_row_is_generated_checked_and_uploaded(self):
        book = FakeBook("✅完了(2026-10-30 09:01) 1000件 → 出力_G予定3")
        code, gas, c, u = self.run_schedule(book)
        self.assertEqual(code, 0)
        self.assertEqual(len(book.appended), 1)
        self.assertEqual(book.appended[0][4], "8梱包")
        gas.return_value.run.assert_called_once()
        self.assertEqual(c.call_args.args[0].sheet, "出力_G予定3")
        self.assertEqual(u.call_args.args[0].sheet, "出力_G予定3")
        self.assertIn("入稿済み", book.results[3])
        # 同じ行は2回実行しない
        book2 = FakeBook("✅完了 → 出力_G予定3")
        self.assertEqual(self.run_schedule(book2)[0], 0)
        self.assertEqual(book2.appended, [])

    def test_row_option_ignores_date(self):
        book = FakeBook("✅完了 → 出力_X")
        self.run_schedule(book, row=2, status="下書き", count=5)
        self.assertEqual(book.appended[0][4], "1クルマ")
        self.assertEqual((book.appended[0][6], book.appended[0][8]), (5, "下書き"))

    def test_ng_stops_before_upload(self):
        book = FakeBook("✅完了 → 出力_X")
        code, _, _, u = self.run_schedule(book, check=2)
        self.assertEqual(code, 2)
        u.assert_not_called()
        self.assertIn("NG", book.results[3])

    def test_generation_error_is_recorded(self):
        book = FakeBook("❌エラー: 会社名が空です")
        code, _, c, _ = self.run_schedule(book)
        self.assertEqual(code, 2)
        c.assert_not_called()
        self.assertIn("会社名が空です", book.results[3])

    def test_other_company_is_refused(self):
        book = FakeBook("")
        book.plan_table = lambda: [PLAN[0], ["2026/10/30", "ArK株式会社", "8梱包", "FALSE", "10"]]
        self.assertEqual(self.run_schedule(book)[0], 1)
        self.assertEqual(book.appended, [])


if __name__ == "__main__":
    unittest.main()
