"""操作画面。app.bat から起動すると、パソコンの中だけで動く画面がブラウザで開く。

画面からできること
  - 出力シート（ヒトマネ出力_…）の一覧と、チェック・入稿の状態を見る
  - チェック：シートを読んでチェックし、結果（report.html）を開く
  - 入稿：止める条件と、募集管理の全件数を確かめてから、ヒトマネに取り込む（裏で upload コマンドを動かし、出力を画面に出す）
  - 取り下げ：掲載開始日の期間を入れて「確認だけ」で件数を見てから、「取り下げる」（今日・同じ条件の確認のファイルを使う）
  - 更新：GitHub に新しい版があるかを確かめ、ボタン1つで最新にする
"""
import html
import io
import json
import os
import secrets
import subprocess
import sys
import threading
import urllib.request
import webbrowser
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlparse

from . import config, workflow

# 更新しても残すもの（各自の設定・鍵・環境・実行記録）
KEEP = ("config/settings.local.json", "config/rules.local.json", "service_account.json", ".venv/", "state/", "output/")


class Job:
    """裏で動かしているコマンド1つ分。出力を1行ずつためて、画面に返す。"""

    def __init__(self, title: str, args: list[str]):
        self.title, self.args = title, args
        self.lines: list[str] = []
        self.code: int | None = None

    def start(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen([sys.executable, "-m", "hitomane_agent", *self.args], cwd=config.ROOT,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     env=env, text=True, encoding="utf-8", errors="replace")
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.append(line.rstrip("\n"))
        self.code = self.proc.wait()

    def to_dict(self, since: int = 0) -> dict:
        return {"title": self.title, "lines": self.lines[since:], "next": len(self.lines),
                "running": self.code is None, "code": self.code}


class App:
    def __init__(self, book=None):
        self.token = secrets.token_urlsafe(16)
        self.job: Job | None = None
        self.lock = threading.Lock()
        self.book = book  # テストではにせの book を渡す

    def _settings(self) -> dict:
        return config.load("settings.json")

    def run(self, title: str, args: list[str]) -> dict:
        with self.lock:
            if self.job and self.job.code is None:
                raise RuntimeError(f"「{self.job.title}」を実行中です。終わってから実行してください")
            self.job = Job(title, args)
            self.job.start()
        return {"ok": True}

    def sheets(self) -> list[dict]:
        from .sheet import Spreadsheet

        names = Spreadsheet(self._settings(), self.book).output_sheet_names()
        reviews, uploaded = workflow.load_state("reviews.json"), workflow.load_state("uploaded.json")
        out = []
        for n in names:
            rv, up = reviews.get(n, {}), uploaded.get(n)
            out.append({"name": n, "status": rv.get("status", ""), "rows": rv.get("rows"),
                        "checked_at": rv.get("checked_at", ""), "uploaded_at": up["uploaded_at"] if up else "",
                        "uploaded_same": bool(up and up.get("hash") == rv.get("hash"))})
        return out

    def check(self, name: str) -> dict:
        ms = workflow.load_manuscript(self._settings(), sheet=name, book=self.book)
        res = workflow.check(ms, config.load("rules.json"))
        return {k: res[k] for k in ("name", "status", "rows", "counts", "sheet_issues")}

    def prepare(self, name: str, total=None) -> dict:
        """入稿の前の確認：止める理由、件数、募集管理の全件数（ログインして読む）。"""
        ms = workflow.load_manuscript(self._settings(), sheet=name, book=self.book)
        problem = workflow.upload_problem(ms)
        if problem:
            return {"ok": False, "problem": problem}
        rv = workflow.load_state("reviews.json")[name]
        if total is None:
            from . import accounts
            from .uploader import HitomaneUploader
            settings = self._settings()
            total = HitomaneUploader(accounts.login_info(settings), settings["hitomane"],
                                     config.OUTPUT_DIR / name).total()
        return {"ok": True, "rows": len(ms.rows), "status": rv["status"],
                "note": workflow.total_note(total, len(ms.rows), config.load("rules.json"))}

    # ---- 取り下げ ----
    def _login_id(self) -> str:
        from . import accounts
        return accounts.login_info(self._settings())["login_id"]

    def takedown_args(self, body: dict) -> tuple[str, list[str]]:
        """「確認だけ」はいつでも、「取り下げる」は今日・同じ条件の「確認だけ」があるときだけ。"""
        from datetime import date

        from . import takedown
        cond = takedown.Conditions(takedown.parse_day(body["from"]), takedown.parse_day(body["to"]))
        if cond.start_from > cond.start_to:
            raise ValueError("期間の「から」が「まで」より後です")
        args = ["takedown", "--from", f"{cond.start_from:%Y/%m/%d}", "--to", f"{cond.start_to:%Y/%m/%d}"]
        if body.get("prepare_only"):
            return f"取り下げの確認：{cond.describe()}", args + ["--prepare-only"]
        p = takedown.find_prepared(self._login_id(), cond, date.today())
        if not p:
            raise RuntimeError("先に、同じ期間で「確認だけ」をしてください（今日のもの）")
        if not p["rows"]:
            raise RuntimeError("取り下げる原稿がありません")
        return f"取り下げ：{cond.describe()}（{p['rows']}件）", args + ["--yes"]

    def prepared(self) -> list[dict]:
        from datetime import date

        from . import takedown
        return takedown.prepared_list(date.today())

    def report(self, name: str) -> bytes:
        path = (config.OUTPUT_DIR / name / "report.html").resolve()
        if config.OUTPUT_DIR.resolve() not in path.parents or not path.exists():
            raise FileNotFoundError("チェック結果がありません。先にチェックしてください")
        return path.read_bytes()

    # ---- 更新 ----
    def update_info(self) -> dict:
        u = self._settings()["update"]
        with urllib.request.urlopen(f"https://api.github.com/repos/{u['repo']}/branches/{u['branch']}", timeout=20) as r:
            commit = json.load(r)["commit"]
        latest = {"sha": commit["sha"], "date": commit["commit"]["committer"]["date"],
                  "message": commit["commit"]["message"].splitlines()[0]}
        current = _version()
        return {"current": current, "latest": latest, "new": current.get("sha") != latest["sha"]}

    def update_from_github(self) -> dict:
        u = self._settings()["update"]
        info = self.update_info()
        with urllib.request.urlopen(f"https://codeload.github.com/{u['repo']}/zip/refs/heads/{u['branch']}",
                                    timeout=120) as r:
            changed = apply_zip(r.read(), u["subdir"])
        _save_version({**info["latest"], "updated_at": datetime.now().isoformat(timespec="seconds")})
        return {"changed": changed}


def apply_zip(data: bytes, subdir: str) -> int:
    """GitHub の ZIP（「リポジトリ名-ブランチ名/hitomane_agent/…」）から hitomane_agent の中身だけを上書きする。
    KEEP に当たるものと、フォルダの外に出るパスは書かない。書き換えたファイルの数を返す。"""
    root = config.ROOT.resolve()
    count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        prefixes = {PurePosixPath(n).parts[0] for n in names}
        base = f"{prefixes.pop()}/{subdir}/" if len(prefixes) == 1 else f"{subdir}/"
        targets = [n for n in names if n.startswith(base)]
        if not targets:
            raise RuntimeError(f"ZIP の中に {subdir} フォルダが見つかりません")
        for n in targets:
            rel = n[len(base):]
            if not rel or any(rel == k or rel.startswith(k) for k in KEEP):
                continue
            dest = (root / rel).resolve()
            if root not in dest.parents:
                continue
            new = z.read(n)
            if dest.exists() and dest.read_bytes() == new:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(new)
            count += 1
    return count


def _version() -> dict:
    p = config.STATE_DIR / "version.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_version(v: dict) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (config.STATE_DIR / "version.json").write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")


PAGE = """<!doctype html><html lang=ja><head><meta charset=utf-8><title>ヒトマネ入稿ツール</title>
<style>
body{font-family:sans-serif;margin:24px;color:#1f2328;max-width:1100px}
table{border-collapse:collapse;width:100%;margin:8px 0 16px}td,th{border:1px solid #d0d7de;padding:6px 8px;font-size:14px;text-align:left}
th{background:#f6f8fa}button{padding:4px 12px;margin-right:4px;cursor:pointer}
.OK{color:#1a7f37;font-weight:bold}.要確認{color:#9a6700;font-weight:bold}.NG{color:#cf222e;font-weight:bold}
#log{background:#0d1117;color:#e6edf3;padding:12px;white-space:pre-wrap;min-height:120px;max-height:420px;overflow:auto;font-size:13px}
#msg{margin:8px 0;padding:8px;background:#fff8c5;display:none}
</style></head><body>
<h1>ヒトマネ入稿ツール</h1>
<p>【AI用】ヒトマネ 求人原稿自動生成 の「ヒトマネ出力_…」シートをチェックして、ヒトマネに取り込みます。
チェックのあとにシートを直したときは、もう一度チェックしてください。</p>
<div id=msg></div>
<h2>出力シート <button onclick="loadSheets()">一覧を読み直す</button></h2>
<table><thead><tr><th>シート</th><th>原稿</th><th>チェック</th><th>入稿</th><th></th></tr></thead><tbody id=sheets>
<tr><td colspan=5>読み込み中…</td></tr></tbody></table>
<h2>取り下げ</h2>
<p>掲載開始日がこの期間の、掲載中の原稿を取り下げます（開始日・終了日を2年前、ステータスを非掲載にして取り込み直します）。
先に「確認だけ」で件数を見てから、「取り下げる」を押してください。</p>
<p>掲載開始日 <input id=tdFrom placeholder="2026/10/01" size=12> 〜 <input id=tdTo placeholder="2026/10/31" size=12>
<button onclick="takedown(true)">確認だけ</button> <button onclick="takedown(false)">取り下げる</button></p>
<table><thead><tr><th>今日の確認</th><th>検索の件数</th><th>取り下げる原稿</th><th>除いた原稿</th><th>確認した時刻</th></tr></thead>
<tbody id=prepared></tbody></table>
<h2>実行の記録</h2><div id=log></div>
<h2>更新</h2><p><button onclick="checkUpdate()">新しい版を確かめる</button> <span id=upd></span></p>
<script>
const T = "__TOKEN__";
const api = (p, body) => fetch(p + (p.includes("?") ? "&" : "?") + "t=" + T, body === undefined ? {} :
  {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})
  .then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.error || r.status); return j; });
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const say = t => { const m = document.getElementById("msg"); m.textContent = t; m.style.display = t ? "block" : "none"; };
function loadSheets() {
  api("/api/sheets").then(list => {
    document.getElementById("sheets").innerHTML = list.length ? list.map(s => `<tr>
      <td>${esc(s.name)}</td><td>${s.rows ?? ""}</td>
      <td><span class="${esc(s.status)}">${esc(s.status || "未実施")}</span> ${esc(s.checked_at)}
        ${s.status ? `<a href="/report?name=${encodeURIComponent(s.name)}&t=${T}" target=_blank>結果を見る</a>` : ""}</td>
      <td>${s.uploaded_same ? "入稿済み " : ""}${esc(s.uploaded_at)}</td>
      <td><button onclick='check(${JSON.stringify(s.name)})'>チェック</button>
          <button onclick='upload(${JSON.stringify(s.name)})' ${s.status && s.status !== "NG" && !s.uploaded_same ? "" : "disabled"}>入稿</button></td>
    </tr>`).join("") : "<tr><td colspan=5>出力シートがありません。GAS の③で原稿を作ってください</td></tr>";
  }).catch(e => say("一覧を読めませんでした: " + e.message));
}
function check(name) {
  say(name + " をチェックしています…");
  api("/api/check", {name}).then(r => { say(`${name}：原稿 ${r.rows}件、判定 ${r.status}`); loadSheets(); })
    .catch(e => say("チェックできませんでした: " + e.message));
}
function upload(name) {
  say(name + "：入稿の前の確認をしています（ヒトマネにログインして全件数を読みます）…");
  api("/api/prepare", {name}).then(r => {
    if (!r.ok) { say("入稿しません: " + r.problem); return; }
    say("");
    const text = `${name} をヒトマネに取り込みます。\\n\\n原稿 ${r.rows}件（チェック ${r.status}）\\n${r.note}` +
      (r.status === "要確認" ? "\\n\\n注意の指摘があります。チェック結果を確かめましたか？" : "") + "\\n\\n取り込みますか？";
    if (!confirm(text)) return;
    api("/api/upload", {name}).then(() => follow(0)).catch(e => say(e.message));
  }).catch(e => say("確認できませんでした: " + e.message));
}
function follow(since) {
  api("/api/job?since=" + since).then(j => {
    const log = document.getElementById("log");
    if (since === 0) log.textContent = "■ " + j.title + "\\n";
    log.textContent += j.lines.map(l => l + "\\n").join(""); log.scrollTop = log.scrollHeight;
    if (j.running) setTimeout(() => follow(j.next), 1500);
    else { log.textContent += j.code === 0 ? "\\n終わりました\\n" : "\\n止まりました（上の記録を見てください）\\n"; loadSheets(); loadPrepared(); }
  });
}
function loadPrepared() {
  api("/api/takedown/prepared").then(list => {
    document.getElementById("prepared").innerHTML = list.length ? list.map(p => `<tr><td>${esc(p.conditions)}</td>
      <td>${p.searched}件</td><td>${p.rows}件</td>
      <td>${esc(Object.entries(p.skipped || {}).map(([k, v]) => k + " " + v + "件").join("、"))}</td>
      <td>${esc(p.prepared_at)}</td></tr>`).join("") : "<tr><td colspan=5>まだありません</td></tr>";
  });
}
function takedown(prepareOnly) {
  const from = document.getElementById("tdFrom").value.trim(), to = document.getElementById("tdTo").value.trim();
  if (!from || !to) { say("掲載開始日の期間を入れてください"); return; }
  if (!prepareOnly && !confirm(`掲載開始日 ${from}〜${to} の掲載中の原稿を取り下げます。\\n\\n` +
      "「今日の確認」の件数を確かめましたか？取り下げますか？")) return;
  say("");
  api("/api/takedown", {from, to, prepare_only: prepareOnly}).then(() => follow(0)).catch(e => say(e.message));
}
function checkUpdate() {
  const u = document.getElementById("upd"); u.textContent = "確かめています…";
  api("/api/update").then(r => {
    if (!r.new) { u.textContent = "最新です（" + r.latest.message + "）"; return; }
    u.innerHTML = "新しい版があります：" + esc(r.latest.message) + " <button id=go>更新する</button>";
    document.getElementById("go").onclick = () => { u.textContent = "更新しています…";
      api("/api/update/github", {}).then(x => u.textContent = x.changed + "ファイルを更新しました。黒い画面を閉じて app.bat を開き直してください")
        .catch(e => u.textContent = "更新できませんでした: " + e.message); };
  }).catch(e => u.textContent = "確かめられませんでした: " + e.message);
}
loadSheets();
loadPrepared();
</script></body></html>"""


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self, query) -> bool:
            # ほかのサイトからこの画面の操作をされないよう、起動のたびに作る合言葉を付けたときだけ受け付ける
            return query.get("t", [""])[0] == app.token

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self._authorized(q):
                return self._send(403, {"error": "この画面は app.bat から開いてください"})
            try:
                if u.path == "/":
                    return self._send(200, PAGE.replace("__TOKEN__", app.token).encode("utf-8"), "text/html; charset=utf-8")
                if u.path == "/api/sheets":
                    return self._send(200, app.sheets())
                if u.path == "/api/job":
                    since = int(q.get("since", ["0"])[0])
                    return self._send(200, app.job.to_dict(since) if app.job else {"lines": [], "running": False})
                if u.path == "/report":
                    return self._send(200, app.report(q.get("name", [""])[0]), "text/html; charset=utf-8")
                if u.path == "/api/update":
                    return self._send(200, app.update_info())
                if u.path == "/api/takedown/prepared":
                    return self._send(200, app.prepared())
            except Exception as e:
                return self._send(500, {"error": html.escape(str(e))})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            u = urlparse(self.path)
            if not self._authorized(parse_qs(u.query)):
                return self._send(403, {"error": "この画面は app.bat から開いてください"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if u.path == "/api/check":
                    return self._send(200, app.check(body["name"]))
                if u.path == "/api/prepare":
                    return self._send(200, app.prepare(body["name"]))
                if u.path == "/api/upload":
                    name = body["name"]
                    problem = workflow.upload_problem(workflow.load_manuscript(app._settings(), sheet=name, book=app.book))
                    if problem:
                        raise RuntimeError(problem)
                    return self._send(200, app.run(f"入稿：{name}", ["upload", "--sheet", name, "--yes"]))
                if u.path == "/api/takedown":
                    return self._send(200, app.run(*app.takedown_args(body)))
                if u.path == "/api/update/github":
                    return self._send(200, app.update_from_github())
            except Exception as e:
                return self._send(500, {"error": html.escape(str(e))})
            self._send(404, {"error": "not found"})

    return Handler


def serve(port: int = 0, open_browser: bool = True, app: App | None = None) -> ThreadingHTTPServer:
    app = app or App()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    server.app = app
    url = f"http://127.0.0.1:{server.server_port}/?t={app.token}"
    print(f"操作画面を開きました: {url}")
    print("この黒い画面を閉じると、操作画面も使えなくなります。")
    if open_browser:
        webbrowser.open(url)
    return server


def main() -> None:
    server = serve()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
