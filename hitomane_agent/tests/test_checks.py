"""入稿前のチェック。"""
import unittest

from hitomane_agent import config
from hitomane_agent.checks import Manuscript, check_sheet, status_of
from hitomane_agent.headers import NEW_FORMAT
from tests.samples import row, table

RULES = config.load("rules.json")


def run(*rows, tbl=None):
    ms = Manuscript("ヒトマネ出力_テスト", tbl if tbl is not None else table(*rows))
    sheet_issues, results = check_sheet(ms, RULES)
    return sheet_issues, results


def messages(issues, severity=None):
    return [f"{i.column}:{i.message}" for i in issues if severity is None or i.severity == severity]


class TestChecks(unittest.TestCase):
    def test_good_row_is_ok(self):
        sheet, results = run(row())
        self.assertEqual(sheet, [])
        self.assertEqual(status_of(results[0]), "OK", messages(results[0]))

    def assertRowError(self, column, **change):
        _, results = run(row(**change))
        errs = [i for i in results[0] if i.severity == "error"]
        self.assertTrue(any(i.column == column for i in errs), messages(results[0]))

    def test_header_must_be_new_format(self):
        t = table(row())
        t[0][5] = "違う見出し"
        sheet, _ = run(tbl=t)
        self.assertEqual(status_of(sheet), "NG")
        self.assertIn("新フォーマット", messages(sheet)[0])

    def test_old_format_is_refused(self):
        t = [["募集番号", "ステータス", "開始日", "終了日", "拠点コード", "拠点"] + [f"列{i}" for i in range(103)],
             ["a"] * 109]
        sheet, _ = run(tbl=t)
        self.assertEqual(status_of(sheet), "NG")
        self.assertIn("旧フォーマット", messages(sheet)[0])

    def test_empty_sheet(self):
        sheet, _ = run(tbl=table())
        self.assertIn("原稿がありません", " ".join(messages(sheet, "error")))

    def test_sheet_error_value(self):
        self.assertRowError("待遇", **{"待遇": "#REF!"})

    def test_not_cp932(self):
        _, results = run(row(**{"PR": "がんばろう😀"}))
        e = [i for i in results[0] if i.column == "PR" and i.severity == "error"]
        self.assertTrue(e and "😀" in e[0].message, messages(results[0]))

    def test_required_blank(self):
        for col in ("募集番号", "拠点コード", "募集職種", "勤務地_市区町村"):
            with self.subTest(col=col):
                self.assertRowError(col, **{col: ""})

    def test_yes_no(self):
        self.assertRowError("寮・社宅あり", **{"寮・社宅あり": "有"})
        self.assertRowError("週払いOK", **{"週払いOK": ""})

    def test_dates(self):
        self.assertRowError("開始日", **{"開始日": "2026-11-17"})
        self.assertRowError("開始日", **{"開始日": "2028/01/01"})  # 終了日より後
        _, results = run(row(**{"開始日": "2026/1/7", "終了日": "2027/1/7"}))  # ゼロなしも読める
        self.assertEqual(status_of(results[0]), "OK", messages(results[0]))

    def test_status_value(self):
        self.assertRowError("ステータス", **{"ステータス": "公開"})

    def test_salary(self):
        self.assertRowError("基本給_最低額", **{"基本給_最低額": "35万"})
        self.assertRowError("基本給_最低額", **{"基本給_最低額": "500000"})

    def test_memo_mismatch(self):
        self.assertRowError("お仕事番号", **{"基本給_最高額": "440000"})
        self.assertRowError("お仕事番号", **{"画像名1": "軽作業(230)"})
        self.assertRowError("お仕事番号", **{"勤務地_市区町村": "泉佐野市", "勤務地_補足": "大阪府泉佐野市"})

    def test_memo_company_is_not_checked(self):
        # メモの会社名は略称のことがある（canal benefits株 と CB株式会社）ので見ない
        _, results = run(row(**{"拠点": "CB株式会社"}))
        self.assertEqual(status_of(results[0]), "OK", messages(results[0]))

    def test_duplicate_code_is_error(self):
        _, results = run(row(), row(**{"勤務地_市区町村": "堺市", "勤務地_補足": "大阪府堺市",
                                        "お仕事番号": "3-261117-1-1-6E-351200-439000-製造(268)-大阪府堺市-テスト株"}))
        self.assertTrue(any(i.column == "募集番号" and i.severity == "error" for i in results[1]))

    def test_duplicate_place_is_warning(self):
        _, results = run(row(), row(**{"募集番号": "test0002"}))
        w = [i for i in results[1] if i.column == "勤務地_市区町村"]
        self.assertTrue(w and w[0].severity == "warning")
        self.assertEqual(status_of(results[1]), "要確認")

    def test_two_branch_codes_is_warning(self):
        sheet, _ = run(row(), row(**{"募集番号": "test0002", "拠点コード": "B002", "勤務地_市区町村": "堺市",
                                     "勤務地_補足": "大阪府堺市",
                                     "お仕事番号": "3-261117-1-1-6E-351200-439000-製造(268)-大阪府堺市-テスト株"}))
        self.assertIn("拠点コード", " ".join(messages(sheet, "warning")))

    def test_usual_blank_is_warning(self):
        _, results = run(row(**{"勤務時間_補足": ""}))
        self.assertEqual(status_of(results[0]), "要確認")

    def test_hash_changes_with_content(self):
        a = Manuscript("x", table(row())).data_hash()
        b = Manuscript("x", table(row(**{"PR": "別の文"}))).data_hash()
        self.assertNotEqual(a, b)

    def test_rules_cover_all_yes_no_columns(self):
        self.assertEqual(len(RULES["yes_no_columns"]), 85)
        self.assertTrue(set(RULES["yes_no_columns"]) <= set(NEW_FORMAT))


if __name__ == "__main__":
    unittest.main()
