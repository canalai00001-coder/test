"""ヒトマネのログイン情報（Q-mateログイン情報シートの「ヒトマネ」の行）。"""
import types
import unittest

from hitomane_agent import accounts, config

HEAD = ["会社名", "ログインID", "パスワード", "CSV取込画面のURL（またはco=の番号）", "メモ"]


class FakeBook:
    def __init__(self, rows, perms=()):
        self.rows, self.perms = rows, list(perms)
        self.opened = []

    def worksheet(self, name):
        self.opened.append(name)
        return types.SimpleNamespace(get_all_values=lambda: [HEAD] + self.rows)

    def list_permissions(self):
        return self.perms


SETTINGS = config.load("settings.json")


class TestLoginInfo(unittest.TestCase):
    def test_reads_hitomane_row(self):
        book = FakeBook([["canal benefits株式会社", "c", "x", "", ""], ["ヒトマネ", "Minami", "pw", "", ""]],
                        [{"type": "user"}])
        self.assertEqual(accounts.login_info(SETTINGS, book),
                         {"login_id": "Minami", "password": "pw", "url": "https://kanri.hitomgr.jp/m66w/"})
        self.assertEqual(book.opened, ["ヒトマネログイン情報"])

    def test_url_column_is_used_when_filled(self):
        book = FakeBook([["ヒトマネ", "Minami", "pw", "https://kanri.hitomgr.jp/other/", ""]])
        self.assertEqual(accounts.login_info(SETTINGS, book)["url"], "https://kanri.hitomgr.jp/other/")

    def test_link_shared_is_refused(self):
        book = FakeBook([["ヒトマネ", "Minami", "pw", "", ""]], [{"type": "anyone", "role": "writer"}])
        with self.assertRaisesRegex(RuntimeError, "制限付き"):
            accounts.login_info(SETTINGS, book)

    def test_missing_row(self):
        with self.assertRaisesRegex(RuntimeError, "『ヒトマネ』の行を足して"):
            accounts.login_info(SETTINGS, FakeBook([["canal benefits株式会社", "c", "x", "", ""]]))

    def test_blank_password(self):
        with self.assertRaisesRegex(RuntimeError, "パスワードが空欄"):
            accounts.login_info(SETTINGS, FakeBook([["ヒトマネ", "Minami", "", "", ""]]))



class MultiBook:
    """シートが複数ある本（無いシートは gspread と同じく WorksheetNotFound）。"""
    def __init__(self, sheets, perms=()):
        self.sheets, self.perms = sheets, list(perms)

    def worksheet(self, name):
        import gspread
        if name not in self.sheets:
            raise gspread.WorksheetNotFound(name)
        return types.SimpleNamespace(get_all_values=lambda: self.sheets[name])

    def list_permissions(self):
        return self.perms


class TestHitomaneSheet(unittest.TestCase):
    def test_own_sheet_without_company_column(self):
        book = MultiBook({"ヒトマネログイン情報": [["ログインID", "パスワード", "URL"], ["Minami", "pw", ""]]})
        self.assertEqual(accounts.login_info(SETTINGS, book)["login_id"], "Minami")

    def test_own_sheet_with_company_column(self):
        book = MultiBook({"ヒトマネログイン情報": [HEAD, ["ヒトマネ", "Minami", "pw", "", ""]]})
        self.assertEqual(accounts.login_info(SETTINGS, book)["password"], "pw")

    def test_falls_back_to_qmate_sheet(self):
        book = MultiBook({"Q-mateログイン情報": [HEAD, ["ヒトマネ", "Minami", "pw", "", ""]]})
        self.assertEqual(accounts.login_info(SETTINGS, book)["login_id"], "Minami")

    def test_neither_sheet(self):
        with self.assertRaisesRegex(RuntimeError, "ヒトマネログイン情報"):
            accounts.login_info(SETTINGS, MultiBook({}))


if __name__ == "__main__":
    unittest.main()
