"""ヒトマネへの取り込み（にせの管理画面で）。"""
import tempfile
import unittest
from pathlib import Path

from hitomane_agent.uploader import HitomaneUploader
from tests import fake_hitomane

OPTS = {"timeout_ms": 20000, "poll_interval_ms": 10, "import_poll_times": 5}


class TestUploader(unittest.TestCase):
    def setUp(self):
        self.srv, self.st, url = fake_hitomane.start()
        self.addCleanup(self.srv.shutdown)
        self.info = {"login_id": "Minami", "password": "pw", "url": url}
        self.out = Path(tempfile.mkdtemp())
        self.csv = self.out / "up.csv"
        self.csv.write_bytes("募集番号,開始日\r\ntest0001,2026/11/17\r\n".encode("cp932"))

    def up(self, files=None, old_format=False, **opts):
        u = HitomaneUploader(self.info, {**OPTS, **opts}, self.out, log=lambda *a: None)
        return u.upload(files or [self.csv], old_format=old_format)

    def test_total(self):
        self.st.total = 49990
        u = HitomaneUploader(self.info, OPTS, self.out, log=lambda *a: None)
        self.assertEqual(u.total(), 49990)

    def test_success(self):
        results = self.up()
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertTrue(r.ok, r.message)
        self.assertIn("完了", r.row_text)
        self.assertEqual(self.st.imports[0]["file"], self.csv.read_bytes())
        self.assertFalse(self.st.imports[0]["dup"])  # 「上書きせずに取り込む」は外したまま
        self.assertTrue(Path(r.screenshot).exists())

    def test_old_format(self):
        r = self.up(old_format=True)[0]
        self.assertTrue(r.ok, r.message)
        self.assertEqual(self.st.imports[0]["file"], self.csv.read_bytes())
        self.assertTrue(self.st.imports[0]["old"])  # 旧原稿形式CSV取込（complete）に送った
        self.assertFalse(self.st.imports[0]["dup"])
        self.assertFalse(self.up()[0].ok is False)  # 新フォーマットはこれまでどおり
        self.assertFalse(self.st.imports[1]["old"])

    def test_unchecks_no_overwrite(self):
        self.st.dup_default = True
        self.assertTrue(self.up()[0].ok)
        self.assertFalse(self.st.imports[0]["dup"])

    def test_error_status(self):
        self.st.import_status = "エラー"
        self.st.import_detail = "3行目：開始日の形式が不正です"
        r = self.up()[0]
        self.assertFalse(r.ok)
        self.assertIn("開始日の形式が不正です", r.row_text)

    def test_error_words_in_detail(self):
        self.st.import_detail = "成功: 0件 エラー: 1件 （8秒）"
        self.assertFalse(self.up()[0].ok)

    def test_success_count_must_match_rows(self):
        # 実物の完了の表示は「成功: 1件 （8秒）」。成功の件数が CSV の件数より少なければ失敗とする
        self.st.import_detail = "成功: 0件 （8秒）"
        r = self.up()[0]
        self.assertFalse(r.ok)
        self.assertIn("1件", r.message)

    def test_real_success_text(self):
        r = self.up()[0]
        self.assertTrue(r.ok, r.message)
        self.assertIn("成功: 1件", r.row_text)

    def test_timeout(self):
        self.st.import_ready_after = -1
        r = self.up(import_poll_times=2)[0]
        self.assertFalse(r.ok)
        self.assertIn("終わりませんでした", r.message)

    def test_several_files_in_order(self):
        second = self.out / "up2.csv"
        second.write_bytes("募集番号,開始日\r\ntest0002,2026/11/17\r\n".encode("cp932"))
        results = self.up([self.csv, second])
        self.assertEqual([r.ok for r in results], [True, True])
        self.assertEqual([i["file"] for i in self.st.imports], [self.csv.read_bytes(), second.read_bytes()])

    def test_stops_after_failed_file(self):
        self.st.import_status = "エラー"
        second = self.out / "up2.csv"
        second.write_bytes(self.csv.read_bytes())
        results = self.up([self.csv, second])
        self.assertEqual(len(results), 1)  # 1つ目が失敗したら、残りは取り込まない
        self.assertEqual(len(self.st.imports), 1)

    def test_password_not_written(self):
        self.up()
        for f in self.out.rglob("*"):
            if f.suffix in (".txt", ".html"):
                self.assertNotIn("pw=pw", f.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
