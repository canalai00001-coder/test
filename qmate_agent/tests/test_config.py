"""settings.local.json での上書きを確かめる。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qmate_agent import config


class TestLocalOverride(unittest.TestCase):
    def test_local_values_win_and_others_stay(self):
        d = Path(tempfile.mkdtemp())
        (d / "settings.json").write_text(json.dumps({
            "a": 1, "schedule_targets": {"通勤": {"gas_webapp_url": "（仮）", "token_env": "T"}}}), encoding="utf-8")
        (d / "settings.local.json").write_text(json.dumps({
            "schedule_targets": {"通勤": {"gas_webapp_url": "https://x/exec"}}}), encoding="utf-8")
        with mock.patch.object(config, "CONFIG_DIR", d):
            s = config.load("settings.json")
        self.assertEqual(s["schedule_targets"]["通勤"], {"gas_webapp_url": "https://x/exec", "token_env": "T"})
        self.assertEqual(s["a"], 1)

    def test_without_local_file(self):
        d = Path(tempfile.mkdtemp())
        (d / "rules.json").write_text('{"b": 2}', encoding="utf-8")
        with mock.patch.object(config, "CONFIG_DIR", d):
            self.assertEqual(config.load("rules.json"), {"b": 2})


if __name__ == "__main__":
    unittest.main()
