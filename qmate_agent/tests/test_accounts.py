"""会社ごとのログイン情報（accounts）。パスワードの保存先（keyring）はにせものに置き換える。"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from qmate_agent import accounts, config

SETTINGS = {"qmate": {"company": "AspiRove株式会社", "upload_url": "https://m.q-mate.jp/job_offers/bulk_new?co=27859",
                      "login_url": "https://m.q-mate.jp/login"}}


class FakeKeyring(types.ModuleType):
    def __init__(self):
        super().__init__("keyring")
        self.store = {}

    def set_password(self, s, u, p):
        self.store[(s, u)] = p

    def get_password(self, s, u):
        return self.store.get((s, u))

    def delete_password(self, s, u):
        self.store.pop((s, u))


class TestAccounts(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.kr = FakeKeyring()
        for p in (mock.patch.object(config, "CONFIG_DIR", Path(self.dir.name)),
                  mock.patch.dict(sys.modules, {"keyring": self.kr}),
                  mock.patch.dict("os.environ", {}, clear=True),
                  mock.patch.object(accounts, "_sheet_book", side_effect=RuntimeError("鍵なし")),
                  mock.patch.dict(accounts._sheet_cache, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.dir.cleanup)

    def test_save_and_use(self):
        accounts.save("ArK株式会社", "ark@example.com", "https://m.q-mate.jp/job_offers/bulk_new?co=11111", "pw1")
        saved = json.loads((Path(self.dir.name) / "accounts.local.json").read_text(encoding="utf-8"))
        self.assertNotIn("pw1", json.dumps(saved))  # パスワードはファイルに書かない
        q = accounts.qmate_config(SETTINGS, "ArK株式会社")
        self.assertEqual((q["login_id"], q["password"], q["upload_url"]),
                         ("ark@example.com", "pw1", "https://m.q-mate.jp/job_offers/bulk_new?co=11111"))
        self.assertEqual(q["login_url"], "https://m.q-mate.jp/login")
        # パスワードを空で保存し直すと、前のパスワードのまま ID だけ変わる
        accounts.save("ArK株式会社", "new@example.com", "11111")
        self.assertEqual(accounts.qmate_config(SETTINGS, "ArK株式会社")["password"], "pw1")
        self.assertEqual(accounts.listing(SETTINGS)[0]["login_id"], "new@example.com")
        accounts.delete("ArK株式会社")
        self.assertEqual(accounts.load(), {})
        self.assertEqual(self.kr.store, {})

    def test_unregistered_and_env_fallback(self):
        with self.assertRaisesRegex(RuntimeError, "見つかりません|登録されていません"):
            accounts.qmate_config(SETTINGS, "ArK株式会社")
        with self.assertRaisesRegex(RuntimeError, "見つかりません|登録されていません"):
            accounts.qmate_config(SETTINGS, "AspiRove株式会社")
        self.assertEqual(accounts.companies(SETTINGS), [])
        with mock.patch.dict("os.environ", {"QMATE_ID": "aspi", "QMATE_PASSWORD": "pw"}):
            q = accounts.qmate_config(SETTINGS, "AspiRove株式会社")
            self.assertEqual((q["login_id"], q["password"]), ("aspi", "pw"))
            self.assertEqual(accounts.companies(SETTINGS), ["AspiRove株式会社"])
            self.assertEqual(accounts.listing(SETTINGS)[0]["co"], "27859")

    def test_input_checks(self):
        with self.assertRaisesRegex(ValueError, "会社番号"):
            accounts.save("A社", "id", "https://example.com/", "pw")
        with self.assertRaisesRegex(ValueError, "パスワード"):
            accounts.save("A社", "id", "123", "")
        self.assertEqual(accounts.parse_co(" 27859 "), "27859")


class FakeBook:
    def __init__(self, values, perms):
        self.values, self.perms = values, perms

    def worksheet(self, name):
        assert name == "Q-mateログイン情報"
        return types.SimpleNamespace(get_all_values=lambda: self.values)

    def list_permissions(self):
        return self.perms


SHEET_VALUES = [["会社名", "ログインID", "パスワード", "CSV取込画面のURL（またはco=の番号）", "メモ"],
                ["ArK株式会社", "ark@example.com", "sheetpw", "https://m.q-mate.jp/job_offers/bulk_new?co=22222", ""],
                ["", "", "", "", "空行"],
                ["B社", "b@example.com", "", "333", ""],
                ["C社", "c@example.com", "cpw", "", "URL は空欄"]]


class TestSheetAccounts(unittest.TestCase):
    def use(self, perms):
        book = FakeBook(SHEET_VALUES, perms)
        for p in (mock.patch.object(accounts, "_sheet_book", return_value=book),
                  mock.patch.dict(accounts._sheet_cache, clear=True),
                  mock.patch.object(accounts, "load", return_value={}),
                  mock.patch.dict("os.environ", {}, clear=True)):
            p.start()
            self.addCleanup(p.stop)

    def test_private_sheet_is_used(self):
        self.use([{"type": "user", "emailAddress": "a@example.com"}])
        q = accounts.qmate_config(dict(SETTINGS, spreadsheet_id="x"), "ArK株式会社")
        self.assertEqual((q["login_id"], q["password"], q["upload_url"]),
                         ("ark@example.com", "sheetpw", "https://m.q-mate.jp/job_offers/bulk_new?co=22222"))
        self.assertEqual(accounts.companies(dict(SETTINGS, spreadsheet_id="x")), ["ArK株式会社", "B社", "C社"])
        self.assertEqual(accounts.qmate_config(dict(SETTINGS, spreadsheet_id="x"), "C社")["upload_url"],
                         "https://m.q-mate.jp/job_offers/bulk_new")
        self.assertIn("空欄", accounts.login_problem(dict(SETTINGS, spreadsheet_id="x"), "B社"))
        listed = accounts.listing(dict(SETTINGS, spreadsheet_id="x"))
        self.assertEqual([(a["company"], a["password"], a["source"]) for a in listed],
                         [("ArK株式会社", True, "スプレッドシート"), ("B社", False, "スプレッドシート"),
                          ("C社", True, "スプレッドシート")])
        self.assertNotIn("sheetpw", json.dumps(listed, ensure_ascii=False))

    def test_link_shared_sheet_is_refused(self):
        self.use([{"type": "anyone", "role": "writer"}])
        with self.assertRaisesRegex(RuntimeError, "制限付き"):
            accounts.qmate_config(dict(SETTINGS, spreadsheet_id="x"), "ArK株式会社")
        self.assertIn("公開", accounts.listing(dict(SETTINGS, spreadsheet_id="x"))[0]["source"])


class TestFillUrl(unittest.TestCase):
    def test_writes_only_blank_url(self):
        values = [["会社名", "ログインID", "パスワード", "CSV取込画面のURL（またはco=の番号）"],
                  ["A社", "a@example.com", "pw", ""],
                  ["B社", "b@example.com", "pw", "https://m.q-mate.jp/job_offers/bulk_new?co=1"]]
        written = []
        ws = types.SimpleNamespace(get_all_values=lambda: values, update_cell=lambda r, c, v: written.append((r, c, v)))
        book = types.SimpleNamespace(worksheet=lambda n: ws)
        url = "https://m.q-mate.jp/job_offers/bulk_new?co=23836"
        with mock.patch.object(accounts, "_sheet_book", return_value=book):
            self.assertTrue(accounts.fill_url(SETTINGS, "A社", url))
            self.assertFalse(accounts.fill_url(SETTINGS, "B社", url))   # 入っている URL は変えない
            self.assertFalse(accounts.fill_url(SETTINGS, "C社", url))   # シートに無い会社
            self.assertFalse(accounts.fill_url(SETTINGS, "A社", "https://m.q-mate.jp/job_offers"))  # co が無い
        self.assertEqual(written, [(2, 4, url)])
