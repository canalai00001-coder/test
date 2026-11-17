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

    def test_overview_shows_last_total(self):
        from hitomane_agent import workflow
        r = self.call("/api/overview")[1]
        self.assertIsNone(r["total"])
        workflow.save_total("Minami", 49990)
        r = self.call("/api/overview")[1]
        self.assertEqual((r["total"], r["limit"], r["left"]), (49990, 50000, 10))
        workflow.save_total("Minami", None)  # 読めなかったときは前の件数のまま
        self.assertEqual(self.call("/api/overview")[1]["total"], 49990)

    def test_checks_do_not_return_password(self):
        info = {"login_id": "Minami", "password": "secret-pw", "url": "u"}
        with mock.patch.object(app_mod.App, "_login_info", return_value=info):
            code, items = self.call("/api/checks")
        self.assertEqual(code, 200)
        self.assertNotIn("secret-pw", json.dumps(items, ensure_ascii=False))
        names = {i["name"]: i["ok"] for i in items}
        self.assertTrue(names["【AI用】スプレッドシートを読める（出力シート 2枚）"])
        self.assertTrue(names["ヒトマネのログイン情報（Minami）"])

    def test_checks_show_login_error(self):
        with mock.patch.object(app_mod.App, "_login_info", side_effect=RuntimeError("パスワードが空欄です")):
            items = self.call("/api/checks")[1]
        self.assertIn({"name": "ヒトマネのログイン情報", "ok": False, "hint": "パスワードが空欄です"}, items)

    def test_login_starts_command(self):
        with mock.patch.object(app_mod.App, "run", return_value={"ok": True}) as run:
            self.assertEqual(self.call("/api/login", {})[0], 200)
        run.assert_called_once_with("ログインの確認と全件数", ["login"])

    def test_takedown_history_newest_first(self):
        from hitomane_agent import takedown
        takedown.record({"login_id": "Minami", "conditions": "A", "rows": 1, "ok": True, "results": []})
        takedown.record({"login_id": "Minami", "conditions": "B", "rows": 2, "ok": False, "results": []})
        h = self.call("/api/takedown/history")[1]
        self.assertEqual([(x["conditions"], x["ok"]) for x in h], [("B", False), ("A", True)])
        self.assertNotIn("results", h[0])

    def test_update_from_zip(self):
        with mock.patch.object(app_mod, "apply_zip", return_value=3) as ap:
            req = urllib.request.Request(f"{self.base}/api/update/zip?t={self.app.token}", data=b"PK..", method="POST")
            with urllib.request.urlopen(req) as r:
                self.assertEqual(json.loads(r.read())["changed"], 3)
        ap.assert_called_once_with(b"PK..", "hitomane_agent")
        self.assertEqual(self.call("/api/version")[1]["message"], "ダウンロードした ZIP から更新")


class TestTakedownGate(TestApp):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(app_mod.App, "_login_id", return_value="Minami")
        p.start()
        self.addCleanup(p.stop)

    def test_prepare_only_is_always_allowed(self):
        title, args = self.app.takedown_args({"from": "2026/10/01", "to": "2026/10/31", "prepare_only": True})
        self.assertEqual(args, ["takedown", "--from", "2026/10/01", "--to", "2026/10/31", "--prepare-only"])

    def test_takedown_needs_prepare_today(self):
        with self.assertRaises(RuntimeError) as e:
            self.app.takedown_args({"from": "2026/10/01", "to": "2026/10/31"})
        self.assertIn("確認だけ", str(e.exception))
        from datetime import date
        from hitomane_agent import takedown
        f = config.OUTPUT_DIR / "t.csv"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
        cond = takedown.Conditions(date(2026, 10, 1), date(2026, 10, 31))
        takedown.save_prepared("Minami", cond, {"rows": 2, "files": [str(f)], "searched": 2, "skipped": {}}, date.today())
        title, args = self.app.takedown_args({"from": "2026/10/1", "to": "2026/10/31"})
        self.assertEqual(args[-1], "--yes")
        self.assertIn("2件", title)
        self.assertEqual(len(self.app.prepared()), 1)
        self.assertEqual((self.app.prepared()[0]["from"], self.app.prepared()[0]["to"]), ("2026/10/01", "2026/10/31"))
        with mock.patch.object(app_mod.App, "run") as run:  # 確認の文のための問い合わせでは実行しない
            code, r = self.call("/api/takedown", {"from": "2026/10/1", "to": "2026/10/31", "preview": True})
        self.assertEqual(code, 200)
        self.assertIn("2件", r["title"])
        run.assert_not_called()

    def test_bad_range(self):
        with self.assertRaises(ValueError):
            self.app.takedown_args({"from": "2026/10/31", "to": "2026/10/01", "prepare_only": True})


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
