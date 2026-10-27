"""AIチェックの結果の扱いと、投稿対象の絞り込みを確かめる（API は呼ばない）。"""
import json
import unittest
from types import SimpleNamespace

from qmate_agent import config
from qmate_agent.__main__ import select_targets
from qmate_agent.ai_review import AIReviewer
from qmate_agent.sheet import Row
from qmate_agent.validate import build_job, job_hash

FCFG = config.load("fields.json")
SHEET = config.load("sheet.json")


class FakeClient:
    def __init__(self, payload, stop_reason="end_turn"):
        text = SimpleNamespace(type="text", text=json.dumps(payload, ensure_ascii=False))
        resp = SimpleNamespace(stop_reason=stop_reason, content=[text])
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: resp))


class TestAIReview(unittest.TestCase):
    def test_issues_are_tagged_ai(self):
        payload = {"issues": [{"severity": "warning", "field": "title", "message": "職種名と仕事内容が合っていません",
                               "suggestion": "食品の検品・梱包"}], "summary": "1件"}
        issues, summary = AIReviewer(client=FakeClient(payload)).review({"title": "x"}, {}, [])
        self.assertEqual((issues[0].source, issues[0].severity), ("ai", "warning"))
        self.assertEqual(summary, "1件")

    def test_refusal_becomes_error(self):
        issues, _ = AIReviewer(client=FakeClient({}, stop_reason="refusal")).review({}, {}, [])
        self.assertEqual(issues[0].severity, "error")


ROW = {
    "求人No": "A-1", "承認": "OK", "職種名": "部品の組立", "雇用形態": "派遣社員",
    "仕事内容": "自動車部品の組付けと目視検査をお願いします。未経験歓迎です。",
    "都道府県": "群馬県", "勤務地住所": "群馬県サンプル市1-1", "最寄り駅": "サンプル駅",
    "給与形態": "時給", "給与額": "1600", "月収例": "256000", "勤務時間": "8:00～17:00",
    "休日": "土日", "年齢下限": "", "年齢上限": "", "性別": "不問", "寮": "あり",
}


class TestSelectTargets(unittest.TestCase):
    def run_select(self, row_values, reviews, posted=None):
        rows = [Row(2, row_values)]
        jobs = [build_job(r, FCFG["fields"]) for r in rows]
        return select_targets(rows, jobs, SHEET, FCFG["fields"], FCFG["rules"], reviews, posted or {})

    def review_of(self, values, status="OK", ai=True):
        return {"A-1": {"hash": job_hash(build_job(Row(2, values), FCFG["fields"])), "status": status, "ai": ai}}

    def test_approved_and_unchanged(self):
        targets, skipped = self.run_select(ROW, self.review_of(ROW))
        self.assertEqual(len(targets), 1)

    def test_not_approved_is_ignored(self):
        targets, skipped = self.run_select(dict(ROW, 承認=""), self.review_of(ROW))
        self.assertEqual((targets, skipped), ([], []))

    def test_changed_after_check(self):
        targets, skipped = self.run_select(dict(ROW, 給与額="1700"), self.review_of(ROW))
        self.assertEqual(targets, [])
        self.assertIn("変わって", skipped[0][2])

    def test_ng_is_skipped(self):
        targets, _ = self.run_select(ROW, self.review_of(ROW, status="NG"))
        self.assertEqual(targets, [])

    def test_already_posted(self):
        h = self.review_of(ROW)["A-1"]["hash"]
        targets, skipped = self.run_select(ROW, self.review_of(ROW), {"A-1": {"hash": h}})
        self.assertEqual(targets, [])
        self.assertIn("投稿済み", skipped[0][2])


if __name__ == "__main__":
    unittest.main()
