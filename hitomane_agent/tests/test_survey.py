"""画面調査（にせの管理画面で）。"""
import tempfile
import unittest
from pathlib import Path

from hitomane_agent import survey
from tests import fake_hitomane

NAMES = ["01_ログイン画面", "02_トップ", "03_ファイル取込ダイアログ", "04_募集管理", "05_予約一覧"]


class Base(unittest.TestCase):
    def setUp(self):
        self.srv, self.st, url = fake_hitomane.start()
        self.addCleanup(self.srv.shutdown)
        self.info = {"login_id": "Minami", "password": "pw", "url": url}
        self.out = Path(tempfile.mkdtemp())

    def run_it(self, **kw):
        return survey.run_survey(self.info, self.out, log=lambda *a: None, **kw)

    def step(self, res, name):
        return next(s for s in res["steps"] if s["name"] == name)


class TestSurvey(Base):
    def test_survey_saves_each_screen(self):
        res = self.run_it()
        self.assertEqual([s["name"] for s in res["steps"]], NAMES)
        self.assertTrue(all(s["ok"] for s in res["steps"]), res["steps"])
        for n in NAMES:
            self.assertTrue((self.out / f"{n}.html").exists(), n)
            self.assertTrue((self.out / f"{n}.png").exists(), n)
            self.assertTrue((self.out / f"{n}_links.txt").exists(), n)
        self.assertEqual(len((self.out / "調査結果.txt").read_text(encoding="utf-8").strip().splitlines()), 5)
        for f in self.out.iterdir():
            if f.suffix in (".html", ".txt"):
                self.assertNotIn("pw=pw", f.read_text(encoding="utf-8"))
        self.assertIn("ファイルを取り込む", (self.out / "03_ファイル取込ダイアログ.html").read_text(encoding="utf-8"))

    def test_wrong_password_stops(self):
        self.info["password"] = "ng"
        res = self.run_it()
        self.assertEqual([s["name"] for s in res["steps"]], NAMES[:1])
        self.assertFalse(res["steps"][0]["ok"])
        self.assertIn("ログインできませんでした", res["steps"][0]["note"])

    def test_forbidden_stops(self):
        self.st.forbidden = True
        res = self.run_it()
        self.assertEqual(len(res["steps"]), 1)
        self.assertIn("403", res["steps"][0]["note"])

    def test_missing_link_continues(self):
        self.st.reserve_link = False
        res = self.run_it()
        self.assertTrue(all(self.step(res, n)["ok"] for n in NAMES[:4]))
        self.assertFalse(self.step(res, NAMES[4])["ok"])
        self.assertIn("見つかりませんでした", self.step(res, NAMES[4])["note"])

    def test_import_is_not_reserved(self):
        self.run_it()
        self.assertFalse(self.st.import_reserved)
        self.assertEqual(self.st.export_reserved, 0)



class TestSample(Base):
    def run_sample(self, **kw):
        return self.run_it(sample="CB93208", poll_interval_ms=10, **kw)

    def test_sample_export_downloads_csv(self):
        res = self.run_sample()
        self.assertTrue(self.step(res, "06_取り出し予約")["ok"], res["steps"])
        self.assertTrue(self.step(res, "07_取り出しファイル")["ok"], res["steps"])
        self.assertEqual((self.out / "取り出し見本.csv").read_bytes(), self.st.csv.encode("utf-8"))
        self.assertEqual(self.st.export_reserved, 1)
        self.assertFalse(self.st.import_reserved)

    def test_sample_not_unique_stops(self):
        self.st.hits = 3
        res = self.run_sample()
        s = self.step(res, "06_取り出し予約")
        self.assertFalse(s["ok"])
        self.assertIn("3件", s["note"])
        self.assertEqual(self.st.export_reserved, 0)
        self.assertNotIn("07_取り出しファイル", [x["name"] for x in res["steps"]])

    def test_sample_export_timeout(self):
        self.st.export_ready_after = -1
        res = self.run_sample(export_poll_times=2)
        s = self.step(res, "07_取り出しファイル")
        self.assertFalse(s["ok"])
        self.assertIn("完了しませんでした", s["note"])
        self.assertFalse((self.out / "取り出し見本.csv").exists())


if __name__ == "__main__":
    unittest.main()
