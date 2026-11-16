"""設定の読み込み（settings.json に settings.local.json を重ねる）。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hitomane_agent import config


class TestConfig(unittest.TestCase):
    def test_local_overrides_settings(self):
        d = Path(tempfile.mkdtemp())
        (d / "settings.json").write_text(json.dumps({"hitomane": {"base_url": "a", "timeout_ms": 1}}), encoding="utf-8")
        (d / "settings.local.json").write_text(json.dumps({"hitomane": {"base_url": "b"}}), encoding="utf-8")
        with mock.patch.object(config, "CONFIG_DIR", d):
            self.assertEqual(config.load("settings.json")["hitomane"], {"base_url": "b", "timeout_ms": 1})

    def test_settings_has_required_keys(self):
        s = config.load("settings.json")
        for k in ("spreadsheet_id", "output_sheet_prefix", "service_account_file", "login_spreadsheet_id",
                  "accounts_sheet", "login_company", "hitomane", "csv"):
            self.assertIn(k, s)
        for k in ("base_url", "timeout_ms", "poll_interval_ms", "export_poll_times"):
            self.assertIn(k, s["hitomane"])
        self.assertEqual(s["spreadsheet_id"], "1sDLw8aMXmkQi9Uy4fhQMf3g4GqKhh7fd8TJEIWe1DzA")
        self.assertEqual(s["hitomane"]["base_url"], "https://kanri.hitomgr.jp/m66w/")
        self.assertEqual(s["login_company"], "ヒトマネ")


if __name__ == "__main__":
    unittest.main()
