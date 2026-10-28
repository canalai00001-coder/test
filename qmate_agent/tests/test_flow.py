"""AI チェック・入稿前の止め条件・Q-mate への入稿操作を確かめる。本物の API や Q-mate には接続しない。"""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from qmate_agent import __main__ as cli
from qmate_agent import config
from qmate_agent.ai_review import AIReviewer
from qmate_agent.checks import Manuscript
from tests.fixtures import ROW, clean_row, table


class FakeClient:
    def __init__(self, payload, stop_reason="end_turn"):
        text = SimpleNamespace(type="text", text=json.dumps(payload, ensure_ascii=False))
        self.sent = {}
        resp = SimpleNamespace(stop_reason=stop_reason, content=[text])

        def create(**kw):
            self.sent = kw
            return resp
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))


class TestAIReview(unittest.TestCase):
    def test_only_review_columns_are_sent(self):
        client = FakeClient({"issues": [{"severity": "warning", "column": "キーワードリスト（複数選択可）",
                                         "message": "寮の記載がないのに寮・社宅あり", "suggestion": "削除"}],
                             "summary": "1件"})
        issues, summary = AIReviewer(client=client).review(dict(ROW, UID="secret-uid"), [])
        self.assertEqual((issues[0].source, summary), ("ai", "1件"))
        self.assertNotIn("secret-uid", client.sent["messages"][0]["content"])
        self.assertIn("メラミン化粧板", client.sent["messages"][0]["content"])

    def test_refusal_becomes_error(self):
        issues, _ = AIReviewer(client=FakeClient({}, "refusal")).review(ROW, [])
        self.assertEqual(issues[0].severity, "error")


class FakeBook:
    def __init__(self, tbl, verdict="✅OK"):
        self.tbl, self.verdict = tbl, verdict

    def manuscript(self, name):
        return Manuscript(name, self.tbl)

    def inspection_verdicts(self):
        return {"出力_test": self.verdict} if self.verdict else {}


class TestUploadGate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(config, "STATE_DIR", self.tmp / "state"),
                        mock.patch.object(config, "OUTPUT_DIR", self.tmp / "out")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def review(self, tbl, status="OK", ai=True):
        cli._save_state("reviews.json", {"出力_test": {"hash": Manuscript("出力_test", tbl).data_hash(),
                                                       "status": status, "ai": ai, "checked_at": "now"}})

    def run_upload(self, book):
        args = SimpleNamespace(sheet="出力_test", dry_run=True, headed=False, yes=True)
        with mock.patch.object(cli, "_spreadsheet", return_value=book), mock.patch("builtins.print") as pr:
            code = cli.cmd_upload(args)
        return code, " ".join(str(c.args[0]) for c in pr.call_args_list)

    def test_ok_reaches_csv(self):
        tbl = table(clean_row())
        self.review(tbl)
        code, out = self.run_upload(FakeBook(tbl))
        self.assertEqual(code, 0)
        self.assertTrue((self.tmp / "out" / "出力_test" / "出力_test.csv").exists())

    def test_rule_check_only_is_enough_by_default(self):
        tbl = table(clean_row())
        self.review(tbl, ai=False)
        self.assertEqual(self.run_upload(FakeBook(tbl))[0], 0)

    def test_ai_required_when_configured(self):
        tbl = table(clean_row())
        self.review(tbl, ai=False)
        load = config.load
        with mock.patch.object(cli.config, "load",
                               lambda n: dict(load(n), require_ai_check=True) if n == "settings.json" else load(n)):
            self.assertIn("AIチェックなし", self.run_upload(FakeBook(tbl))[1])

    def test_not_checked(self):
        self.assertIn("check をしていません", self.run_upload(FakeBook(table(clean_row())))[1])

    def test_changed_after_check(self):
        self.review(table(clean_row()))
        self.assertIn("変わっています", self.run_upload(FakeBook(table(clean_row(給与_上限="450000"))))[1])

    def test_ng(self):
        tbl = table(clean_row())
        self.review(tbl, status="NG")
        self.assertIn("NG", self.run_upload(FakeBook(tbl))[1])

    def test_inspection_not_ok(self):
        tbl = table(clean_row())
        self.review(tbl)
        self.assertIn("検品シートの判定", self.run_upload(FakeBook(tbl, verdict="❌NG"))[1])


# ---- Q-mate の画面のかわり ---------------------------------------------------
PAGES = {
    "/user_sessions/new": "<form method=post action=/user_sessions><input type=email name=email>"
                          "<input type=password name=password><button type=submit>ログイン</button></form>",
    "/home": "<p>ホーム</p>",
}


def import_page():
    # Q-mate の CSV取込画面に合わせた仮の画面。取り込みは受付後に裏で処理され、
    # 「最後に受付したCSV取込」の欄が 処理中 → 成功 / エラー と変わる。
    log = Handler.log
    if Handler.pending:
        Handler.pending -= 1
        log = log.replace("{status}", "処理中")
    else:
        log = log.replace("{status}", Handler.final)
    return ("<form method=post action=/import enctype=multipart/form-data><input type=file name=file id=file>"
            "<input type=submit id=csv_import_submit value=アップロード></form>"
            f"<div id=csv_import_log>最後に受付したCSV取込 {log}</div>"
            "<p>テンプレート出力 成功</p>")


class Handler(BaseHTTPRequestHandler):
    uploaded = b""
    log = "前回.csv 成功 2026/10/01 10:00:00"
    pending = 0
    final = ""

    def _send(self, code, body="", location=None):
        self.send_response(code)
        if location:
            self.send_header("Location", location)
        data = f"<!doctype html><meta charset=utf-8>{body}".encode()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        self._send(200, import_page() if path == "/import" else PAGES.get(path, "not found"))

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/user_sessions":
            ok = b"password=pw" in body
            return self._send(302, location="/home" if ok else "/user_sessions/new")
        Handler.uploaded = body
        Handler.log = "x.csv {status} 2026/10/27 21:00:00"
        Handler.pending = 2
        Handler.final = "成功" if "求人ボックス用職種名".encode() in body else "エラー内容を見る"
        self._send(302, location="/import")

    def log_message(self, *a):
        pass


@unittest.skipUnless(os.environ.get("PLAYWRIGHT_CHROMIUM_PATH") or Path.home().joinpath(".cache/ms-playwright").exists(),
                     "ブラウザがありません")
class TestUploader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.srv.server_port}"
        cls.cfg = dict(config.load("settings.json")["qmate"], login_url=base + "/user_sessions/new",
                       upload_url=base + "/import", result_poll_interval_ms=10, timeout_ms=10000)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def upload(self, tbl, pw="pw", **cfg):
        from qmate_agent.csv_export import to_csv_bytes
        from qmate_agent.uploader import QmateUploader
        tmp = Path(tempfile.mkdtemp())
        csv_path = tmp / "x.csv"
        csv_path.write_bytes(to_csv_bytes(Manuscript("x", tbl)))
        with mock.patch.dict(os.environ, {"QMATE_ID": "a@example.com", "QMATE_PASSWORD": pw}):
            return QmateUploader(dict(self.cfg, **cfg), out_dir=tmp).upload(csv_path, "x")

    def test_success(self):
        r = self.upload(table(clean_row()))
        self.assertTrue(r.ok, r)
        self.assertIn("メラミン化粧板".encode(), Handler.uploaded)

    def test_gives_up_while_processing(self):
        r = self.upload(table(clean_row()), result_poll_times=1)
        self.assertFalse(r.ok)
        self.assertIn("処理中", r.page_text)

    def test_error_text_is_failure(self):
        r = self.upload([["UID"], ["1"]])
        self.assertFalse(r.ok)
        self.assertIn("エラー", r.message)

    def test_wrong_password(self):
        r = self.upload(table(clean_row()), pw="bad")
        self.assertFalse(r.ok)
        self.assertIn("ログインできません", r.message)


if __name__ == "__main__":
    unittest.main()
