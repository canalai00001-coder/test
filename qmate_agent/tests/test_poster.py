"""モックのフォームに対して、入力 → 読み戻し照合 → 保存 の流れを確かめる。"""
import copy
import os
import tempfile
import unittest
from pathlib import Path

from qmate_agent import config

try:
    from playwright.sync_api import sync_playwright  # noqa: F401
    from qmate_agent.poster import QmatePoster
    HAS_PW = True
except ImportError:
    HAS_PW = False

MOCK = (Path(__file__).parent / "mock_qmate_form.html").resolve().as_uri()

JOB = {
    "job_no": "A-1", "title": "部品の組立", "employment_type": "派遣社員",
    "description": "自動車部品の組付けと目視検査です。", "prefecture": "群馬県",
    "address": "群馬県サンプル市1-1", "station": "サンプル駅", "wage_type": "時給",
    "wage": "1,600", "monthly_income": "256000", "work_hours": "8:00～17:00", "holiday": "土日",
    "age_min": "", "age_max": "", "gender": "不問", "dorm": "あり",
}


def form_cfg():
    cfg = copy.deepcopy(config.load("qmate_form.json"))
    cfg["new_job_url"] = MOCK
    cfg["skip_login"] = True
    return cfg


@unittest.skipUnless(HAS_PW, "playwright が入っていません")
class TestPoster(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def poster(self):
        return QmatePoster(form_cfg(), auth_file=self.tmp / "none.json", shots_dir=self.tmp)

    def test_fill_verify_and_save(self):
        r = self.poster().run([JOB])[0]
        self.assertTrue(r.ok, r)
        self.assertEqual(r.message, "下書き保存しました")
        self.assertTrue(Path(r.screenshot).exists())

    def test_mismatch_stops_before_save(self):
        # 職種名が maxlength=10 で切られる → 照合で止まる
        job = dict(JOB, title="自動車部品の組立・検査スタッフ")
        r = self.poster().run([job])[0]
        self.assertFalse(r.ok)
        self.assertEqual([m["field"] for m in r.mismatches], ["title"])

    def test_unknown_option_is_error(self):
        r = self.poster().run([dict(JOB, prefecture="大阪府")])[0]
        self.assertFalse(r.ok)
        self.assertIn("エラー", r.message)


if __name__ == "__main__":
    unittest.main()
