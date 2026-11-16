"""操作画面（にせのスプレッドシートで）。"""
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

from hitomane_agent import app as app_mod
from hitomane_agent import config
from tests.samples import row, table


class FakeSheet:
    def __init__(self, title, values):
        self.title, self.values = title, values

    def get_all_values(self):
        return self.values


class FakeBook:
    def __init__(self, sheets):
        self.sheets = sheets

    def worksheets(self):
        return list(self.sheets.values())

    def worksheet(self, name):
        return self.sheets[name]


class TestApp(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        for name, value in (("OUTPUT_DIR", d / "output"), ("STATE_DIR", d / "state")):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.book = FakeBook({
            "マニュアル": FakeSheet("マニュアル", [["x"]]),
            "ヒトマネ出力_A": FakeSheet("ヒトマネ出力_A", table(row())),
            "ヒトマネ出力_B": FakeSheet("ヒトマネ出力_B", table(row(**{"募集番号": ""}))),
        })
        self.app = app_mod.App(book=self.book)
        self.server = app_mod.serve(open_browser=False, app=self.app)
        import threading
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def call(self, path, body=None, token=True):
        url = self.base + path + ((("&" if "?" in path else "?") + "t=" + self.app.token) if token else "")
        req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                data = r.read()
                return r.status, (json.loads(data) if r.headers.get_content_type() == "application/json" else data)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_needs_token(self):
        self.assertEqual(self.call("/api/sheets", token=False)[0], 403)

    def test_page(self):
        code, page = self.call("/")
        self.assertEqual(code, 200)
        self.assertIn(self.app.token.encode(), page)

    def test_lists_output_sheets_only(self):
        code, sheets = self.call("/api/sheets")
        self.assertEqual([s["name"] for s in sheets], ["ヒトマネ出力_A", "ヒトマネ出力_B"])
        self.assertEqual(sheets[0]["status"], "")

    def test_check_and_report(self):
        code, r = self.call("/api/check", {"name": "ヒトマネ出力_A"})
        self.assertEqual((code, r["status"]), (200, "OK"))
        code, r = self.call("/api/check", {"name": "ヒトマネ出力_B"})
        self.assertEqual(r["status"], "NG")
        code, page = self.call("/report?name=" + urllib.request.quote("ヒトマネ出力_B"))
        self.assertIn("空欄です（必須）", page.decode("utf-8"))
        self.assertEqual(self.call("/api/sheets")[1][0]["status"], "OK")

    def test_report_outside_output_is_refused(self):
        code, _ = self.call("/report?name=" + urllib.request.quote("../state"))
        self.assertEqual(code, 500)

    def test_prepare(self):
        self.assertIn("チェックをしていません", self.app.prepare("ヒトマネ出力_A", total=10)["problem"])
        self.app.check("ヒトマネ出力_A")
        r = self.app.prepare("ヒトマネ出力_A", total=49999)
        self.assertTrue(r["ok"])
        self.assertEqual(r["rows"], 1)
        self.assertIn("49,999件", r["note"])
        self.app.check("ヒトマネ出力_B")
        self.assertIn("NG", self.app.prepare("ヒトマネ出力_B", total=10)["problem"])

    def test_upload_refused_without_check(self):
        with mock.patch.object(app_mod.App, "run") as run:
            code, r = self.call("/api/upload", {"name": "ヒトマネ出力_A"})
        self.assertEqual(code, 500)
        self.assertIn("チェックをしていません", r["error"])
        run.assert_not_called()

    def test_upload_starts_command(self):
        self.app.check("ヒトマネ出力_A")
        with mock.patch.object(app_mod.App, "run", return_value={"ok": True}) as run:
            code, _ = self.call("/api/upload", {"name": "ヒトマネ出力_A"})
        self.assertEqual(code, 200)
        run.assert_called_once_with("入稿：ヒトマネ出力_A", ["upload", "--sheet", "ヒトマネ出力_A", "--yes"])


class TestApplyZip(unittest.TestCase):
    def test_keeps_local_files(self):
        root = Path(tempfile.mkdtemp())
        (root / "config").mkdir()
        (root / "config" / "settings.local.json").write_text("mine", encoding="utf-8")
        (root / "a.py").write_text("old", encoding="utf-8")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("test-branch/hitomane_agent/a.py", "new")
            z.writestr("test-branch/hitomane_agent/config/settings.local.json", "theirs")
            z.writestr("test-branch/qmate_agent/x.py", "q")
            z.writestr("test-branch/hitomane_agent/../evil.py", "x")
        with mock.patch.object(config, "ROOT", root):
            n = app_mod.apply_zip(buf.getvalue(), "hitomane_agent")
        self.assertEqual(n, 1)
        self.assertEqual((root / "a.py").read_text(encoding="utf-8"), "new")
        self.assertEqual((root / "config" / "settings.local.json").read_text(encoding="utf-8"), "mine")
        self.assertFalse((root / "x.py").exists())
        self.assertFalse((root.parent / "evil.py").exists())


if __name__ == "__main__":
    unittest.main()
