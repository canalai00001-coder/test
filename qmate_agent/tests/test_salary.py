"""給与設定シート（salary）と、その金額帯での生成。"""
import random
import unittest
from types import SimpleNamespace
from unittest import mock

from qmate_agent import config, salary
from qmate_agent import generator as g
from tests.test_generator import NOW, bank, dorm_req, dorm_sheets

RULES = config.load("rules.json")
TABLE = [salary.HEADERS,
         ["通勤", "7軽め", "夜勤あり", "", "月給", 330000, "", 10000, "マニュアルより"],
         ["通勤", "1クルマ", "", "", "月給", "35万", "", 10000, ""],
         ["通勤", "1クルマ", "夜勤なし", "ArK株式会社", "月給", "320,000", 400000, "", "ArK だけ固定"],
         ["入寮", "", "", "", "時給", 1300, 1625, 50, ""],
         ["", "", "", "", "", "", "", "", "空行"]]


class TestSheet(unittest.TestCase):
    def test_parse_and_match(self):
        rules = salary.parse(TABLE)
        self.assertEqual(len(rules), 4)
        self.assertEqual(rules[1]["lower"], 350000)  # 「35万」も読める
        m = lambda *a: (salary.match(rules, *a) or {}).get("row")
        self.assertEqual(m("通勤", "7軽め", True, "AspiRove株式会社"), 2)
        self.assertIsNone(m("通勤", "7軽め", False, "AspiRove株式会社"))
        self.assertEqual(m("通勤", "1クルマ", False, "AspiRove株式会社"), 3)
        self.assertEqual(m("通勤", "1クルマ", False, "ArK株式会社"), 4)  # 条件を多く書いた行が優先
        self.assertEqual(m("入寮", "6重め", True, "GritMate株式会社"), 5)

    def test_bad_value_is_error(self):
        with self.assertRaisesRegex(ValueError, "3行目の「給与_下限」"):
            salary.parse([salary.HEADERS, ["通勤", "", "", "", "月給", 300000, "", "", ""],
                          ["通勤", "", "", "", "月給", "三十万", "", "", ""]])

    def test_default_rows_are_the_manual_floor(self):
        rows = salary.parse([salary.HEADERS] + salary.default_rows(RULES))
        r = salary.match(rows, "通勤", "7軽め", True, "X社")
        self.assertEqual((r["lower"], r["width"], r["upper"]), (RULES["salary_floor"]["軽め"]["夜勤あり"], 10000, None))
        self.assertEqual(len(rows), 14)


class TestAmounts(unittest.TestCase):
    def gen(self, rule, n=50, **kw):
        req = g.Request(category="1クルマ", company="AspiRove株式会社", count=n, night="夜勤あり",
                        salary_pattern="基本", salary_rule=rule, **kw)
        return g.Generator(bank(), [], rng=random.Random(5), now=NOW).generate(req).rows

    def test_width_10000_is_same_as_before(self):
        rule = salary.parse(TABLE)[1]
        rows = self.gen(rule)
        lows = [int(r["給与_下限"]) for r in rows]
        self.assertTrue(all(350000 <= x <= 359999 for x in lows))
        self.assertEqual(len(set(lows)), len(lows))  # 重ならない
        self.assertTrue(all(int(r["給与_上限"]) == g.js_round(int(r["給与_下限"]) * 1.25) for r in rows))
        self.assertTrue(all(r["メモ"].split("-")[5] == r["給与_下限"] for r in rows))
        self.assertTrue(all(r["給与形態|必須"] == "月給" for r in rows))

    def test_fixed_values(self):
        rule = salary.parse(TABLE)[2]
        rows = self.gen(rule, n=3)
        self.assertEqual({(r["給与_下限"], r["給与_上限"]) for r in rows}, {("320000", "400000")})

    def test_upper_with_width_moves_together(self):
        rule = {"row": 9, "form": "月給", "lower": 330000, "upper": 420000, "width": 1000}
        for r in self.gen(rule):
            self.assertEqual(int(r["給与_上限"]) - int(r["給与_下限"]), 90000)

    def test_dorm_hourly_from_sheet(self):
        rule = salary.parse(TABLE)[3]
        b = g.load_bank(dorm_sheets(), {"重め"}, dorm=True)
        req = dorm_req(salary_rule=rule, count=3)
        rows = g.Generator(b, [], rng=random.Random(1), now=NOW).generate(req).rows
        for r in rows:
            lo, up = int(r["給与_下限"]), int(r["給与_上限"])
            self.assertTrue(1300 <= lo <= 1349 and up - lo == 325)
            self.assertEqual(r["給与形態|必須"], "時給")
            self.assertIn(f"〈時給〉{lo}円〜{up}円", r["詳細な給与情報"])


class TestCreateSheet(unittest.TestCase):
    def test_created_once_with_current_rules(self):
        from qmate_agent import __main__ as cli
        made = {}
        book = SimpleNamespace(table_or_none=lambda name: made.get(name),
                               create_table_sheet=lambda name, rows, note: made.__setitem__(name, rows))
        with mock.patch.object(cli, "_spreadsheet", return_value=book):
            rules = cli._salary_rules(config.load("settings.json"), RULES)
            self.assertIn("給与設定", made)
            self.assertEqual(len(rules), 14)
            self.assertEqual(len(cli._salary_rules(config.load("settings.json"), RULES)), 14)
