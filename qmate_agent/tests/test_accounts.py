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
                  mock.patch.dict("os.environ", {}, clear=True)):
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
        with self.assertRaisesRegex(RuntimeError, "登録されていません"):
            accounts.qmate_config(SETTINGS, "ArK株式会社")
        with self.assertRaisesRegex(RuntimeError, "登録されていません"):
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
