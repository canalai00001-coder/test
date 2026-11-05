"""操作画面（app）を確かめる。スプレッドシート・Q-mate・GitHub には接続しない。"""
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

from qmate_agent import app, config


def github_zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(f"test-claude-relaxed-clarke-nk8kc9/{name}", data)
    return buf.getvalue()


class TestApplyZip(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "config").mkdir()
        (self.root / "config" / "settings.local.json").write_text("自分のURL", encoding="utf-8")
        (self.root / "service_account.json").write_text("鍵", encoding="utf-8")
        (self.root / "qmate_agent").mkdir()
        (self.root / "qmate_agent" / "checks.py").write_text("古い", encoding="utf-8")
        self.p = mock.patch.object(config, "ROOT", self.root)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_updates_tool_but_keeps_local_files(self):
        data = github_zip({
            "README.md": "リポジトリ直下（対象外）",
            "qmate_agent/qmate_agent/checks.py": "新しい",
            "qmate_agent/config/settings.json": "{}",
            "qmate_agent/config/settings.local.json": "上書きしてはいけない",
            "qmate_agent/service_account.json": "上書きしてはいけない",
            "qmate_agent/state/schedule.json": "上書きしてはいけない",
            "qmate_agent/../evil.txt": "外に出てはいけない",
        })
        changed = app.apply_zip(data, "qmate_agent")
        self.assertEqual(changed, 2)
        self.assertEqual((self.root / "qmate_agent" / "checks.py").read_text(encoding="utf-8"), "新しい")
        self.assertEqual((self.root / "config" / "settings.local.json").read_text(encoding="utf-8"), "自分のURL")
        self.assertEqual((self.root / "service_account.json").read_text(encoding="utf-8"), "鍵")
        self.assertFalse((self.root / "state").exists())
        self.assertFalse((self.root.parent / "evil.txt").exists())
        self.assertFalse((self.root / "README.md").exists())

    def test_wrong_zip(self):
        with self.assertRaises(RuntimeError):
            app.apply_zip(github_zip({"other/a.txt": "x"}), "qmate_agent")


class TestArgs(unittest.TestCase):
    def test_schedule_and_takedown_args(self):
        a = app.App()
        self.assertEqual(a.schedule_args({"row": "3", "dry_run": True})[1],
                         ["schedule", "--yes", "--row", "3", "--dry-run"])
        title, args = a.takedown_args({"company": "AspiRove株式会社", "date_from": "2026-10-01", "date_to": "2026-10-22",
                                       "memo": "", "status": "公開"})
        self.assertEqual(args, ["takedown", "--company", "AspiRove株式会社", "--yes", "--from", "2026-10-01",
                                "--to", "2026-10-22", "--status", "公開"])


class TestEngineSwitch(unittest.TestCase):
    def test_switch_saves_to_local_and_keeps_other_values(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "settings.json").write_text(json.dumps({"schedule_targets": {
                "通勤": {"engine": "python", "gas_webapp_url": ""}, "入寮": {"engine": "gas"}}}), encoding="utf-8")
            (d / "settings.local.json").write_text(json.dumps({"schedule_targets": {
                "通勤": {"gas_webapp_url": "https://example/exec"}}}), encoding="utf-8")
            with mock.patch.object(config, "CONFIG_DIR", d):
                a = app.App()
                self.assertEqual(a.engines(), {"通勤": "python"})
                self.assertEqual(a.set_engine({"target": "通勤", "engine": "gas"}), {"通勤": "gas"})
                t = config.load("settings.json")["schedule_targets"]["通勤"]
                self.assertEqual((t["engine"], t["gas_webapp_url"]), ("gas", "https://example/exec"))
                with self.assertRaises(ValueError):
                    a.set_engine({"target": "入寮", "engine": "python"})


class TestServer(unittest.TestCase):
    def test_token_required_and_job_started(self):
        server = app.serve(open_browser=False)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(base + "/api/checks")
            self.assertEqual(e.exception.code, 403)
            started = []
            with mock.patch.object(app.Job, "start", lambda self: started.append(self.args)):
                req = urllib.request.Request(f"{base}/api/schedule?t={server.app.token}", method="POST",
                                             data=json.dumps({"row": 2}).encode(), headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req).read()
            self.assertEqual(started, [["schedule", "--yes", "--row", "2"]])
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
