import unittest

from qmate_agent import config
from qmate_agent.sheet import Row
from qmate_agent.validate import build_job, check_duplicates, parse_int, run_rules

FCFG = config.load("fields.json")
FIELDS, RULES = FCFG["fields"], FCFG["rules"]

BASE = {
    "求人No": "A-1", "職種名": "部品の組立", "雇用形態": "派遣社員",
    "仕事内容": "自動車部品の組付けと目視検査をお願いします。未経験歓迎です。",
    "都道府県": "群馬県", "勤務地住所": "群馬県サンプル市1-1", "最寄り駅": "サンプル駅",
    "給与形態": "時給", "給与額": "1,600", "月収例": "25.6万円", "勤務時間": "8:00～17:00",
    "休日": "土日", "年齢下限": "", "年齢上限": "", "性別": "不問", "寮": "あり",
}


def job_of(**over):
    v = dict(BASE)
    v.update(over)
    return build_job(Row(2, v), FIELDS)


def errors(job):
    return [i for i in run_rules(job, FIELDS, RULES) if i.severity == "error"]


class TestRules(unittest.TestCase):
    def test_parse_int(self):
        self.assertEqual(parse_int("1,600円"), 1600)
        self.assertEqual(parse_int("25.6万円"), 256000)
        self.assertEqual(parse_int("１６００"), 1600)
        self.assertIsNone(parse_int("応相談"))

    def test_clean_row_passes(self):
        self.assertEqual(run_rules(job_of(), FIELDS, RULES), [])

    def test_required_and_enum(self):
        keys = {i.field for i in errors(job_of(仕事内容="", 雇用形態="派遣"))}
        self.assertEqual(keys, {"description", "employment_type"})

    def test_age_reversed(self):
        self.assertIn("age_min", {i.field for i in errors(job_of(年齢下限="50", 年齢上限="20"))})

    def test_min_wage(self):
        self.assertIn("wage", {i.field for i in errors(job_of(給与額="900", 月収例=""))})

    def test_monthly_income_out_of_range_is_warning(self):
        issues = run_rules(job_of(月収例="560000"), FIELDS, RULES)
        self.assertEqual([(i.field, i.severity) for i in issues], [("monthly_income", "warning")])

    def test_prefecture_address_mismatch(self):
        self.assertIn("address", {i.field for i in errors(job_of(勤務地住所="福岡県サンプル市"))})

    def test_gender_restriction_warns(self):
        issues = run_rules(job_of(性別="女性のみ"), FIELDS, RULES)
        self.assertEqual([i.field for i in issues], ["gender"])

    def test_duplicates(self):
        self.assertIn("A-1", check_duplicates([job_of(), job_of()]))


if __name__ == "__main__":
    unittest.main()
