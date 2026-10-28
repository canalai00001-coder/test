import unittest

from qmate_agent import config
from qmate_agent.checks import Manuscript, check_sheet, find_emoji, parse_memo, status_of
from qmate_agent.csv_export import to_csv_bytes
from tests.fixtures import HEADERS, ROW, clean_row, table

RULES = config.load("rules.json")


def issues_of(*rows):
    return check_sheet(Manuscript("出力_test", table(*rows)), RULES)


def cols(issues, severity=None):
    return sorted({i.column for i in issues if severity is None or i.severity == severity})


class TestMemo(unittest.TestCase):
    def test_parse(self):
        m = parse_memo(ROW["メモ"])
        self.assertEqual((m.job_no, m.salary_min, m.salary_max, m.image_no, m.location, m.company),
                         ("6", 352290, 440363, "52", "埼玉県入間郡越生町", "canal benefits株式会社"))

    def test_company_with_hyphen(self):
        self.assertEqual(parse_memo("22-261020-1-1-12-1-2-3-東京都-A-B株式会社/H").company, "A-B株式会社")


class TestRules(unittest.TestCase):
    def test_clean_row_has_no_issues(self):
        self.assertEqual(issues_of(clean_row())[0], [])

    def test_real_template_row(self):
        # テンプレートの実例（10/22以前の原稿）は絵文字と年間休日125日が残っている
        issues = issues_of(ROW)[0]
        self.assertEqual(status_of(issues), "要確認")
        self.assertEqual(cols(issues), ["休日休暇", "勤務時間", "待遇・福利厚生", "応募資格・条件"])

    def test_emoji_detection_ignores_decorations(self):
        self.assertEqual(find_emoji("★◎■◆●○▼▲※【】"), [])
        self.assertEqual(find_emoji("✨🏡⚠️☎️"), ["☎", "⚠", "✨", "🏡"])

    def test_required_empty(self):
        self.assertEqual(cols(issues_of(clean_row(仕事内容=""))[0], "error"), ["仕事内容"])

    def test_trial_period_column_with_same_name(self):
        # 実際の出力シートには試用期間の「給与形態」列が後ろにもう一つある（空欄のことが多い）
        tbl = table(clean_row())
        tbl[0].append("給与形態")
        tbl[1].append("")
        ms = Manuscript("出力_test", tbl)
        self.assertEqual(ms.rows[0]["給与形態"], "月給")
        self.assertEqual(check_sheet(ms, RULES)[0], [])

    def test_blank_age_limit_becomes_nashi(self):
        ms = Manuscript("出力_test", table(clean_row(年齢制限の有無="")))
        self.assertEqual(ms.fill_blanks(RULES["blank_defaults"]), ["年齢制限の有無"])
        self.assertEqual(check_sheet(ms, RULES)[0], [])
        self.assertIn(",なし,", to_csv_bytes(ms).decode())

    def test_age_limit_kept_when_filled(self):
        ms = Manuscript("出力_test", table(clean_row(年齢制限の有無="あり", 年齢制限事由="例外事由3のイ")))
        self.assertEqual(ms.fill_blanks(RULES["blank_defaults"]), [])
        self.assertEqual(ms.rows[0]["年齢制限の有無"], "あり")

    def test_salary_vs_memo(self):
        self.assertEqual(cols(issues_of(clean_row(給与_下限="352000"))[0], "error"), ["給与_下限"])

    def test_salary_floor(self):
        memo = "22-261022-1-1-1-340000-400000-52-埼玉県入間郡越生町-GritMate株式会社/A"
        issues = issues_of(clean_row(メモ=memo, 給与_下限="340000", 給与_上限="400000"))[0]
        self.assertTrue(any("クルマ・夜勤ありの給与下限 350,000" in i.message for i in issues))

    def test_image_and_location_vs_memo(self):
        issues = issues_of(clean_row(**{"求人ページ用画像1": "53", "勤務地：市区町村": "比企郡"}))[0]
        self.assertEqual(cols(issues, "error"), ["勤務地：市区町村", "求人ページ用画像1"])

    def test_night_mismatch(self):
        r = clean_row(勤務時間="【時間帯（日勤のみ／夜勤なし）】8:00〜17:00")
        self.assertIn("求人ボックス用職種名", cols(issues_of(r)[0], "error"))

    def test_banned_keyword(self):
        issues = issues_of(clean_row(**{"キーワードリスト（複数選択可）": "製造,土日祝休み"}))[0]
        self.assertEqual(cols(issues, "warning"), ["キーワードリスト（複数選択可）"])

    def test_boxjob_title_too_long(self):
        self.assertIn("求人ボックス用職種名", cols(issues_of(clean_row(求人ボックス用職種名="あ" * 51))[0], "error"))

    def test_age_limit_needs_reason(self):
        self.assertEqual(cols(issues_of(clean_row(年齢制限の有無="あり"))[0], "error"), ["年齢制限事由"])

    def test_duplicates_across_rows(self):
        a, b = issues_of(clean_row(), clean_row())
        self.assertEqual(cols(a, "warning"), ["勤務地：市区町村", "求人ボックス用職種名"])


class TestCsv(unittest.TestCase):
    def test_header_and_multiline_kept(self):
        data = to_csv_bytes(Manuscript("x", table(ROW))).decode("utf-8")
        self.assertTrue(data.startswith("UID,更新種別|必須,"))
        self.assertIn('"🎯 🎯 【誰でも即戦力】\nメラミン化粧板', data)
        self.assertEqual(data.count("\r\n"), 2)  # 見出しと1行（セル内の改行は \n のまま）

    def test_hash_changes_when_sheet_changes(self):
        self.assertNotEqual(Manuscript("x", table(ROW)).data_hash(),
                            Manuscript("x", table(clean_row())).data_hash())


if __name__ == "__main__":
    unittest.main()
