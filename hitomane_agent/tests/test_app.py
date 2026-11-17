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


COMPANIES = [{"company": "GritMate株式会社", "code": "o3h3", "url": "https://kanri.hitomgr.jp/o3h3/"},
             {"company": "canal benefits株式会社", "code": "m66w", "url": "https://kanri.hitomgr.jp/m66w/"}]


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
        p = mock.patch.object(app_mod.App, "_companies", return_value=COMPANIES)
        p.start()
        self.addCleanup(p.stop)
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
        acct = {"total": 49999, "branches": [{"code": "B001", "name": "テスト株式会社"}]}
        self.assertIn("チェックをしていません", self.app.prepare("ヒトマネ出力_A", "m66w", acct)["problem"])
        self.app.check("ヒトマネ出力_A")
        r = self.app.prepare("ヒトマネ出力_A", "m66w", acct)
        self.assertTrue(r["ok"])
        self.assertEqual((r["rows"], r["company"], r["branches"]), (1, "canal benefits株式会社", "テスト株式会社（B001）"))
        self.assertIn("49,999件", r["note"])
        self.assertEqual(self.call("/api/companies")[1][1]["total"], 49999)  # 読んだ全件数は会社ごとに覚える
        self.app.check("ヒトマネ出力_B")
        self.assertIn("NG", self.app.prepare("ヒトマネ出力_B", "m66w", acct)["problem"])

    def test_prepare_stops_on_other_company_branch(self):
        self.app.check("ヒトマネ出力_A")
        acct = {"total": 10, "branches": [{"code": "G001", "name": "GritMate株式会社"}]}
        r = self.app.prepare("ヒトマネ出力_A", "o3h3", acct)
        self.assertFalse(r["ok"])
        self.assertIn("GritMate株式会社の拠点にない拠点コードがあります：B001", r["problem"])

    def test_company_is_required_and_checked(self):
        self.app.check("ヒトマネ出力_A")
        with mock.patch.object(app_mod.App, "run") as run:
            code, r = self.call("/api/upload", {"name": "ヒトマネ出力_A"})
            self.assertIn("会社を選んでください", r["error"])
            code, r = self.call("/api/upload", {"name": "ヒトマネ出力_A", "company": "zzzz"})
            self.assertIn("ありません", r["error"])
        run.assert_not_called()

    def test_upload_refused_without_check(self):
        with mock.patch.object(app_mod.App, "run") as run:
            code, r = self.call("/api/upload", {"name": "ヒトマネ出力_A", "company": "m66w"})
        self.assertEqual(code, 500)
        self.assertIn("チェックをしていません", r["error"])
        run.assert_not_called()

    def test_upload_starts_command(self):
        self.app.check("ヒトマネ出力_A")
        with mock.patch.object(app_mod.App, "run", return_value={"ok": True}) as run:
            code, _ = self.call("/api/upload", {"name": "ヒトマネ出力_A", "company": "o3h3"})
        self.assertEqual(code, 200)
        run.assert_called_once_with("入稿：ヒトマネ出力_A → GritMate株式会社",
                                    ["upload", "--sheet", "ヒトマネ出力_A", "--company", "o3h3", "--yes"])

    def test_uploaded_is_shown_per_company(self):
        from hitomane_agent import workflow
        from hitomane_agent.checks import Manuscript
        from hitomane_agent.uploader import UploadResult
        self.app.check("ヒトマネ出力_A")
        ms = Manuscript("ヒトマネ出力_A", table(row()))
        workflow.record_upload(ms, [UploadResult("a.csv", True, "")], "m66w", "canal benefits株式会社")
        self.assertTrue(self.call("/api/sheets?company=m66w")[1][0]["uploaded_same"])
        self.assertFalse(self.call("/api/sheets?company=o3h3")[1][0]["uploaded_same"])

    def test_companies_with_last_total(self):
        from hitomane_agent import workflow
        workflow.save_total("o3h3", 49990, "GritMate株式会社")
        cs = self.call("/api/companies")[1]
        self.assertEqual([(c["code"], c["total"], c["left"]) for c in cs], [("o3h3", 49990, 10), ("m66w", None, None)])
        workflow.save_total("o3h3", None)  # 読めなかったときは前の件数のまま
        self.assertEqual(self.call("/api/companies")[1][0]["total"], 49990)

    def test_checks_do_not_return_password(self):
        info = {"login_id": "Minami", "password": "secret-pw", "url": "u"}
        with mock.patch.object(app_mod.App, "_login_info", return_value=info):
            code, items = self.call("/api/checks")
        self.assertEqual(code, 200)
        self.assertNotIn("secret-pw", json.dumps(items, ensure_ascii=False))
        names = {i["name"]: i["ok"] for i in items}
        self.assertTrue(names["【AI用】スプレッドシートを読める（出力シート 2枚）"])
        self.assertTrue(names["ヒトマネの会社（2社：GritMate株式会社、canal benefits株式会社）"])
        self.assertTrue(names["ヒトマネのログイン情報（Minami）"])

    def test_checks_show_login_error(self):
        with mock.patch.object(app_mod.App, "_login_info", side_effect=RuntimeError("パスワードが空欄です")):
            items = self.call("/api/checks")[1]
        self.assertIn({"name": "ヒトマネのログイン情報", "ok": False, "hint": "パスワードが空欄です"}, items)

    def test_login_starts_command(self):
        with mock.patch.object(app_mod.App, "run", return_value={"ok": True}) as run:
            self.assertEqual(self.call("/api/login", {"company": "o3h3"})[0], 200)
            self.assertEqual(self.call("/api/login", {"all": True})[0], 200)
        self.assertEqual(run.call_args_list[0].args, ("ログインの確認：GritMate株式会社", ["login", "--company", "o3h3"]))
        self.assertEqual(run.call_args_list[1].args, ("全社のログインの確認", ["login", "--all"]))

    def test_takedown_history_per_company(self):
        from hitomane_agent import takedown
        takedown.record({"account": "m66w", "login_id": "Minami", "conditions": "A", "rows": 1, "ok": True, "results": []})
        takedown.record({"account": "m66w", "login_id": "Minami", "conditions": "B", "rows": 2, "ok": False, "results": []})
        takedown.record({"account": "o3h3", "login_id": "Minami", "conditions": "C", "rows": 3, "ok": True, "results": []})
        h = self.call("/api/takedown/history?company=m66w")[1]
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
    def test_prepare_only_is_always_allowed(self):
        title, args = self.app.takedown_args({"from": "2026/10/01", "to": "2026/10/31", "prepare_only": True,
                                              "company": "o3h3"})
        self.assertEqual(args, ["takedown", "--company", "o3h3", "--from", "2026/10/01", "--to", "2026/10/31",
                                "--prepare-only"])
        self.assertIn("GritMate株式会社", title)

    def test_takedown_needs_prepare_today_of_same_company(self):
        body = {"from": "2026/10/01", "to": "2026/10/31", "company": "m66w"}
        with self.assertRaises(RuntimeError) as e:
            self.app.takedown_args(body)
        self.assertIn("確認だけ", str(e.exception))
        from datetime import date
        from hitomane_agent import takedown
        f = config.OUTPUT_DIR / "t.csv"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
        cond = takedown.Conditions(date(2026, 10, 1), date(2026, 10, 31))
        takedown.save_prepared("m66w", cond, {"rows": 2, "files": [str(f)], "searched": 2, "skipped": {}}, date.today())
        with self.assertRaises(RuntimeError):  # 別の会社の確認は使えない
            self.app.takedown_args({**body, "company": "o3h3"})
        self.assertEqual(self.app.prepared("o3h3"), [])
        title, args = self.app.takedown_args({**body, "from": "2026/10/1"})
        self.assertEqual(args[-1], "--yes")
        self.assertIn("2件", title)
        self.assertEqual(len(self.app.prepared("m66w")), 1)
        self.assertEqual((self.app.prepared("m66w")[0]["from"], self.app.prepared("m66w")[0]["to"]),
                         ("2026/10/01", "2026/10/31"))
        with mock.patch.object(app_mod.App, "run") as run:  # 確認の文のための問い合わせでは実行しない
            code, r = self.call("/api/takedown", {**body, "preview": True})
        self.assertEqual(code, 200)
        self.assertIn("2件", r["title"])
        run.assert_not_called()

    def test_bad_range(self):
        with self.assertRaises(ValueError):
            self.app.takedown_args({"from": "2026/10/31", "to": "2026/10/01", "prepare_only": True, "company": "m66w"})


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
