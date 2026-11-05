"""操作画面。app.bat から起動すると、パソコンの中だけで動く画面がブラウザで開く。

画面からできること
  - 入稿：入稿予定表と取り下げ予定表の行を見て、今日の行（または選んだ1行）を実行する
  - 取り下げ：会社・作成日の期間・メモを指定して、Q-mate の原稿を取り下げる
  - 更新：GitHub に新しい版があるかを確かめ、ボタン1つで最新にする（ダウンロードした ZIP からも更新できる）
  - 比較：GAS で作った出力シートと、同じ予約内容でツールが作った原稿を見比べる（生成をツールに切り替える前の確認）
  - 設定の確認：ログイン情報・合言葉・ウェブアプリの URL・サービスアカウントの鍵がそろっているか

実行そのものは、これまでと同じコマンド（python -m qmate_agent schedule など）を裏で動かし、
画面にはその出力をそのまま表示する。
"""
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
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse

from . import config

# 更新しても残すもの（各自の設定・鍵・環境・実行記録）。ZIP の中にあっても上書きしない
KEEP = ("config/settings.local.json", "service_account.json", ".venv/", "state/", "output/")


class Job:
    """裏で動かしているコマンド1つ分。出力を1行ずつためて、画面に返す。"""

    def __init__(self, title: str, args: list[str]):
        self.title, self.args = title, args
        self.lines: list[str] = []
        self.code: int | None = None
        self.started = datetime.now()

    def start(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen([sys.executable, "-m", "qmate_agent", *self.args], cwd=config.ROOT,
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
    def __init__(self):
        self.token = secrets.token_urlsafe(16)
        self.job: Job | None = None
        self.lock = threading.Lock()

    # ---- 実行 ----
    def run(self, title: str, args: list[str]) -> dict:
        with self.lock:
            if self.job and self.job.code is None:
                raise RuntimeError(f"「{self.job.title}」を実行中です。終わってから実行してください")
            self.job = Job(title, args)
            self.job.start()
        return {"ok": True}

    def schedule_args(self, body: dict) -> tuple[str, list[str]]:
        args = ["schedule", "--yes"]
        title = "今日の行を実行"
        if body.get("row"):
            args += ["--row", str(int(body["row"]))]
            title = f"入稿予定表 {int(body['row'])}行目を実行"
        if body.get("takedown_row"):
            args += ["--takedown-row", str(int(body["takedown_row"]))]
            title = f"取り下げ予定表 {int(body['takedown_row'])}行目を実行"
        if body.get("force"):
            args.append("--force")
        return title, args + self._common(body)

    def takedown_args(self, body: dict) -> tuple[str, list[str]]:
        args = ["takedown", "--company", body["company"], "--yes"]
        for key, opt in (("date_from", "--from"), ("date_to", "--to"), ("memo", "--memo"), ("status", "--status")):
            if body.get(key):
                args += [opt, str(body[key])]
        title = f"取り下げ（{body['company']}）" + ("：取り出しと分割だけ" if body.get("dry_run") else "")
        return title, args + self._common(body)

    def outputs(self) -> list[str]:
        from .sheet import Spreadsheet

        settings = config.load("settings.json")
        t = settings["schedule_targets"]["通勤"]
        return Spreadsheet(dict(settings, spreadsheet_id=t["spreadsheet_id"])).output_sheet_names()

    @staticmethod
    def _common(body: dict) -> list[str]:
        return (["--dry-run"] if body.get("dry_run") else []) + (["--headed"] if body.get("headed") else [])

    # ---- 画面に出す情報 ----
    def overview(self) -> dict:
        from . import schedule as sc
        from .sheet import Spreadsheet

        settings = config.load("settings.json")
        today = date.today()
        book = Spreadsheet(settings)
        fmt = lambda d: d.strftime("%Y/%m/%d") if d else ""
        plans = [{"row": p.row, "date": fmt(p.run_date), "today": p.run_date == today, "company": p.company,
                  "category": p.category, "night": "夜勤あり" if p.night else "夜勤なし", "commute": p.commute or "通勤",
                  "status": p.status or "公開", "count": p.count, "title": p.title_choice}
                 for p in sc.read_plan(book.plan_table(), today)]
        tds = [{"row": r.row, "date": fmt(r.run_date), "today": r.run_date == today, "company": r.company,
                "from": fmt(r.date_from), "to": fmt(r.date_to), "memo": r.memo, "status": r.status or "公開"}
               for r in sc.read_takedown_plan(book.plan_table(settings.get("takedown_sheet", "取り下げ予定表")), today)]
        results = self._results(book, settings)
        for p in plans:
            p["result"] = results["plan"].get(p["row"], "")
        for r in tds:
            r["result"] = results["takedown"].get(r["row"], "")
        return {"today": fmt(today), "plans": plans, "takedowns": tds, "companies": [settings["qmate"].get("company")]}

    @staticmethod
    def _results(book, settings) -> dict:
        out = {}
        for key, sheet in (("plan", settings["plan_sheet"]), ("takedown", settings.get("takedown_sheet", "取り下げ予定表"))):
            table = book.plan_table(sheet)
            out[key] = {}
            if table:
                head = [str(h).strip() for h in table[0]]
                if "実行結果" in head:
                    c = head.index("実行結果")
                    out[key] = {i: str(r[c]) for i, r in enumerate(table[1:], start=2) if c < len(r) and r[c]}
        return out

    def checks(self) -> list[dict]:
        settings = config.load("settings.json")
        items = [("サービスアカウントの鍵（service_account.json）",
                  (config.ROOT / settings["service_account_file"]).exists(), "qmate_agent フォルダに置いてください"),
                 ("Q-mate のログイン ID（QMATE_ID）", bool(os.environ.get("QMATE_ID")), "setx QMATE_ID ログインID"),
                 ("Q-mate のパスワード（QMATE_PASSWORD）", bool(os.environ.get("QMATE_PASSWORD")), "setx QMATE_PASSWORD パスワード")]
        for c, t in settings["schedule_targets"].items():
            items.append((f"{c}用 GAS のウェブアプリの URL", t.get("gas_webapp_url", "").startswith("https://"),
                          "config\\settings.local.json に書いてください"))
            items.append((f"{c}用の合言葉（{t['token_env']}）", bool(os.environ.get(t["token_env"])),
                          f"setx {t['token_env']} 合言葉"))
        return [{"name": n, "ok": ok, "hint": h} for n, ok, h in items]

    # ---- 更新 ----
    def update_info(self) -> dict:
        u = config.load("settings.json")["update"]
        current = _version()
        with urllib.request.urlopen(f"https://api.github.com/repos/{u['repo']}/branches/{u['branch']}", timeout=20) as r:
            commit = json.load(r)["commit"]
        latest = {"sha": commit["sha"], "date": commit["commit"]["committer"]["date"],
                  "message": commit["commit"]["message"].splitlines()[0]}
        return {"current": current, "latest": latest, "new": current.get("sha") != latest["sha"]}

    def update_from_github(self) -> dict:
        u = config.load("settings.json")["update"]
        info = self.update_info()
        url = f"https://codeload.github.com/{u['repo']}/zip/refs/heads/{u['branch']}"
        with urllib.request.urlopen(url, timeout=120) as r:
            data = r.read()
        changed = apply_zip(data, u["subdir"])
        _save_version({"sha": info["latest"]["sha"], "date": info["latest"]["date"],
                       "message": info["latest"]["message"], "updated_at": datetime.now().isoformat(timespec="seconds")})
        return {"changed": changed, **self._after_update()}

    def update_from_zip(self, data: bytes) -> dict:
        u = config.load("settings.json")["update"]
        changed = apply_zip(data, u["subdir"])
        _save_version({"sha": "", "date": "", "message": "ダウンロードした ZIP から更新",
                       "updated_at": datetime.now().isoformat(timespec="seconds")})
        return {"changed": changed, **self._after_update()}

    @staticmethod
    def _after_update() -> dict:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(config.ROOT / "requirements.txt")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return {"pip_ok": r.returncode == 0, "pip": (r.stdout + r.stderr)[-2000:]}


def apply_zip(data: bytes, subdir: str) -> int:
    """GitHub の ZIP（「リポジトリ名-ブランチ名/qmate_agent/…」）から qmate_agent の中身だけを上書きする。

    KEEP に当たるものと、フォルダの外に出るパスは書かない。書き換えたファイルの数を返す。
    """
    root = config.ROOT.resolve()
    count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        prefixes = {PurePosixPath(n).parts[0] for n in names}
        # ZIP の一番上が「test-…」のようなフォルダ1つなら、その中の qmate_agent を見る
        base = (f"{prefixes.pop()}/{subdir}/" if len(prefixes) == 1 else f"{subdir}/")
        targets = [n for n in names if n.startswith(base)]
        if not targets:
            raise RuntimeError(f"ZIP の中に {subdir} フォルダが見つかりません。GitHub の［Download ZIP］で落としたファイルを選んでください")
        for n in targets:
            rel = n[len(base):]
            if not rel or any(rel == k or rel.startswith(k) for k in KEEP):
                continue
            dest = (root / rel).resolve()
            if root not in dest.parents:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            new = z.read(n)
            if dest.exists() and dest.read_bytes() == new:
                continue
            dest.write_bytes(new)
            count += 1
    return count


def _version() -> dict:
    p = config.STATE_DIR / "version.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_version(v: dict) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (config.STATE_DIR / "version.json").write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")


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
            return query.get("t", [""])[0] == app.token or self.headers.get("X-Token") == app.token

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self._authorized(q):
                return self._send(403, {"error": "この画面は app.bat から開いてください"})
            try:
                if u.path == "/":
                    return self._send(200, PAGE.replace("__TOKEN__", app.token).encode("utf-8"), "text/html; charset=utf-8")
                if u.path == "/api/overview":
                    return self._send(200, app.overview())
                if u.path == "/api/checks":
                    return self._send(200, app.checks())
                if u.path == "/api/job":
                    since = int(q.get("since", ["0"])[0])
                    return self._send(200, app.job.to_dict(since) if app.job else {"lines": [], "running": False})
                if u.path == "/api/update":
                    return self._send(200, app.update_info())
                if u.path == "/api/outputs":
                    return self._send(200, app.outputs())
            except Exception as e:
                return self._send(500, {"error": str(e)})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            u = urlparse(self.path)
            if not self._authorized(parse_qs(u.query)):
                return self._send(403, {"error": "この画面は app.bat から開いてください"})
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                if u.path == "/api/update/zip":
                    return self._send(200, app.update_from_zip(data))
                body = json.loads(data or b"{}")
                if u.path == "/api/schedule":
                    return self._send(200, app.run(*app.schedule_args(body)))
                if u.path == "/api/takedown":
                    return self._send(200, app.run(*app.takedown_args(body)))
                if u.path == "/api/compare":
                    return self._send(200, app.run(f"比較：{body['sheet']}", ["compare", "--gas-sheet", body["sheet"]]))
                if u.path == "/api/update/github":
                    return self._send(200, app.update_from_github())
            except Exception as e:
                return self._send(500, {"error": str(e)})
            self._send(404, {"error": "not found"})

    return Handler


def serve(port: int = 0, open_browser: bool = True) -> ThreadingHTTPServer:
    app = App()
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


PAGE = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Q-mate 入稿ツール</title>
<style>
:root{--bg:#f5f6f8;--card:#fff;--ink:#1f2328;--sub:#59636e;--line:#d8dde3;--accent:#1f6feb;--danger:#cf222e;--ok:#1a7f37;--warn:#9a6700}
*{box-sizing:border-box}body{margin:0;font-family:"Yu Gothic UI","Meiryo",sans-serif;background:var(--bg);color:var(--ink);font-size:14px}
header{background:#24292f;color:#fff;padding:12px 20px;display:flex;align-items:center;gap:16px}
header h1{font-size:16px;margin:0;font-weight:600}header span{color:#aab3bd;font-size:12px}
nav{display:flex;gap:4px;padding:0 20px;background:#fff;border-bottom:1px solid var(--line)}
nav button{border:0;background:none;padding:12px 16px;font-size:14px;cursor:pointer;color:var(--sub);border-bottom:2px solid transparent}
nav button.on{color:var(--ink);border-bottom-color:var(--accent);font-weight:600}
main{padding:20px;max-width:1200px;margin:0 auto}section{display:none}section.on{display:block}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;margin-bottom:16px}
.card h2{font-size:15px;margin:0 0 12px}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}th{color:var(--sub);font-weight:600;background:#fafbfc}
tr.today td{background:#fff8c5}.btn{border:1px solid var(--line);background:#fff;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:13px}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}.btn.danger{background:var(--danger);border-color:var(--danger);color:#fff}
.btn:disabled{opacity:.5;cursor:not-allowed}.row{display:flex;gap:12px;flex-wrap:wrap;align-items:end;margin-bottom:12px}
label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--sub)}input,select{padding:6px 8px;border:1px solid var(--line);border-radius:6px;font-size:13px}
.opts{display:flex;gap:16px;margin:8px 0 12px;font-size:13px}.opts label{flex-direction:row;align-items:center;color:var(--ink)}
pre{background:#0d1117;color:#e6edf3;padding:12px;border-radius:8px;height:320px;overflow:auto;font-size:12px;white-space:pre-wrap;margin:0}
.note{color:var(--sub);font-size:12px;margin:4px 0 0}.card>p.note{margin-bottom:12px}.ok{color:var(--ok)}.ng{color:var(--danger)}.warn{color:var(--warn)}
.status{font-size:13px;margin-bottom:8px}.empty{color:var(--sub);padding:12px 0}
</style></head><body>
<header><h1>Q-mate 入稿ツール</h1><span id="today"></span></header>
<nav><button data-tab="post" class="on">入稿</button><button data-tab="takedown">取り下げ</button><button data-tab="compare">比較</button><button data-tab="update">更新</button><button data-tab="check">設定の確認</button></nav>
<main>
<section id="post" class="on">
  <div class="card"><h2>入稿予定表</h2>
    <div class="opts"><label><input type="checkbox" id="p_dry"> 入稿しない（生成・チェック・CSV 作成まで）</label>
      <label><input type="checkbox" id="p_headed"> 入稿のブラウザを表示する</label>
      <label><input type="checkbox" id="p_force"> 実行済みの行ももう一度実行する</label></div>
    <div class="row"><button class="btn primary" id="run_today">今日の行をすべて実行</button><button class="btn" onclick="load()">表を読み直す</button></div>
    <p class="note">黄色の行が今日の行です。入稿予定表と取り下げ予定表の、今日の行をまとめて実行します。</p>
    <div id="plans"></div></div>
  <div class="card"><h2>取り下げ予定表</h2><div id="takedowns"></div></div>
</section>
<section id="takedown">
  <div class="card"><h2>原稿の取り下げ</h2>
    <p class="note">Q-mate のテンプレート出力で原稿を取り出し、更新種別を「削除」にして 10,000 件ずつ取り込みます。<b>削除した原稿は元に戻せません。</b></p>
    <div class="row">
      <label>会社<select id="t_company"></select></label>
      <label>作成日から（空欄=最初から）<input type="date" id="t_from"></label>
      <label>作成日まで（空欄=最後まで）<input type="date" id="t_to"></label>
      <label>メモに含む文字（任意）<input id="t_memo" placeholder="例：-2-2-7"></label>
      <label>対象ステータス<select id="t_status"><option>公開</option><option>下書き</option><option>下書き＋公開</option><option>終了</option><option>全てのステータス</option></select></label>
    </div>
    <p class="note">1日だけなら「から」と「まで」に同じ日付を入れてください。作成日は求人メモの「22-<b>261104</b>-…」の部分です。</p>
    <div class="opts"><label><input type="checkbox" id="t_headed"> ブラウザを表示する</label></div>
    <div class="row"><button class="btn" id="t_dry">取り出しと件数の確認だけ（Q-mate は変えない）</button><button class="btn danger" id="t_run">取り下げる</button></div>
  </div>
</section>
<section id="compare">
  <div class="card"><h2>GAS とツールで作った原稿の比較（通勤用）</h2>
    <p class="note">GAS で作った出力シートを選ぶと、同じ予約内容（実行設定の行から自動で探します）でツールが原稿を作り、列ごとに比べます。入稿も使用履歴の記録もしません。最後に「作りが違う列: 0列」と出れば同じ形です。</p>
    <div class="row"><button class="btn" onclick="loadOutputs()">出力シートを読み込む</button></div>
    <div id="outputs"></div></div>
</section>
<section id="update">
  <div class="card"><h2>ツールの更新</h2><div id="ver" class="status">確認しています…</div>
    <div class="row"><button class="btn primary" id="u_github">GitHub から最新にする</button><button class="btn" onclick="checkUpdate()">新しい版があるか確認</button></div>
    <p class="note">ダウンロード済みの ZIP から更新する：<input type="file" id="u_zip" accept=".zip"> <button class="btn" id="u_zip_btn">この ZIP で更新</button></p>
    <p class="note">settings.local.json・service_account.json・.venv・実行記録（state）・出力（output）は上書きしません。更新が終わったら、黒い画面と操作画面を閉じて app.bat を開き直してください。</p>
    <div id="u_result" class="status"></div></div>
</section>
<section id="check"><div class="card"><h2>設定の確認</h2><div id="checks"></div>
  <p class="note">setx で登録したものは、登録したあとに app.bat を開き直すと反映されます。</p></div></section>
<div class="card"><h2 id="job_title">実行の記録</h2><div id="job_state" class="status"></div><pre id="log"></pre></div>
</main>
<script>
const T="__TOKEN__";const api=(p,o={})=>fetch(p+(p.includes("?")?"&":"?")+"t="+T,o).then(async r=>{const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j});
const post=(p,b)=>api(p,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{document.querySelectorAll("nav button,section").forEach(x=>x.classList.remove("on"));b.classList.add("on");document.getElementById(b.dataset.tab).classList.add("on");if(b.dataset.tab==="check")loadChecks();if(b.dataset.tab==="update")checkUpdate();if(b.dataset.tab==="compare")loadOutputs()});
const opt=()=>({dry_run:p_dry.checked,headed:p_headed.checked,force:p_force.checked});
async function load(){plans.innerHTML=takedowns.innerHTML='<div class="empty">読み込んでいます…</div>';
 try{const d=await api("/api/overview");today.textContent="今日："+d.today;
  t_company.innerHTML=d.companies.map(c=>`<option>${esc(c)}</option>`).join("");
  plans.innerHTML=d.plans.length?`<table><tr><th>行</th><th>実行日</th><th>会社</th><th>職種</th><th>夜勤</th><th>通勤/入寮</th><th>ステータス</th><th>原稿数</th><th>職種名選択</th><th>実行結果</th><th></th></tr>`+d.plans.map(p=>`<tr class="${p.today?"today":""}"><td>${p.row}</td><td>${esc(p.date)}</td><td>${esc(p.company)}</td><td>${esc(p.category)}</td><td>${p.night}</td><td>${esc(p.commute)}</td><td>${esc(p.status)}</td><td>${p.count}</td><td>${esc(p.title)}</td><td>${esc(p.result)}</td><td><button class="btn" onclick="runRow(${p.row},'${esc(p.status)}',${p.count})">この行を実行</button></td></tr>`).join("")+"</table>":'<div class="empty">行がありません</div>';
  takedowns.innerHTML=d.takedowns.length?`<table><tr><th>行</th><th>実行日</th><th>会社</th><th>作成日から</th><th>作成日まで</th><th>メモ</th><th>ステータス</th><th>実行結果</th><th></th></tr>`+d.takedowns.map(r=>`<tr class="${r.today?"today":""}"><td>${r.row}</td><td>${esc(r.date)}</td><td>${esc(r.company)}</td><td>${esc(r.from)}</td><td>${esc(r.to)}</td><td>${esc(r.memo)}</td><td>${esc(r.status)}</td><td>${esc(r.result)}</td><td><button class="btn danger" onclick="runTdRow(${r.row})">この行を実行</button></td></tr>`).join("")+"</table>":'<div class="empty">行がありません</div>';
 }catch(e){plans.innerHTML=`<div class="ng">読み込めませんでした：${esc(e.message)}</div>`;takedowns.innerHTML=""}}
async function start(p,b,msg){if(msg&&!confirm(msg))return;try{await post(p,b);since=0;log.textContent="";poll()}catch(e){alert(e.message)}}
run_today.onclick=()=>start("/api/schedule",opt(),"入稿予定表・取り下げ予定表の今日の行を実行します。\n取り下げ予定表の行は Q-mate の原稿を削除します（元に戻せません）。よろしいですか？");
function runRow(row,status,count){start("/api/schedule",{...opt(),row},`入稿予定表 ${row}行目（${status}・${count}件）を実行します。よろしいですか？`)}
function runTdRow(row){start("/api/schedule",{...opt(),takedown_row:row},`取り下げ予定表 ${row}行目を実行します。\nQ-mate の原稿を削除します（元に戻せません）。よろしいですか？`)}
const tBody=()=>({company:t_company.value,date_from:t_from.value,date_to:t_to.value,memo:t_memo.value.trim(),status:t_status.value,headed:t_headed.checked});
const span=b=>!b.date_from&&!b.date_to?"全期間":b.date_from===b.date_to?b.date_from:`${b.date_from||"最初"}〜${b.date_to||"最後"}`;
t_dry.onclick=()=>start("/api/takedown",{...tBody(),dry_run:true});
t_run.onclick=()=>{const b=tBody();start("/api/takedown",b,`${b.company} の「${b.status}」の原稿のうち、作成日：${span(b)}${b.memo?"・メモに「"+b.memo+"」を含む":""}ものを削除します。\n元には戻せません。よろしいですか？`)};
let since=0,timer=null;
async function poll(){clearTimeout(timer);try{const j=await api("/api/job?since="+since);if(j.title)job_title.textContent="実行の記録："+j.title;
 if(j.lines.length){log.textContent+=j.lines.join("\n")+"\n";log.scrollTop=log.scrollHeight}since=j.next??since;
 job_state.innerHTML=j.running?'<span class="warn">実行中…（この画面を閉じても止まりませんが、黒い画面は閉じないでください）</span>':(j.code===0?'<span class="ok">終わりました</span>':j.code==null?"":`<span class="ng">止まりました（コード ${j.code}）。記録を確認してください</span>`);
 if(j.running)timer=setTimeout(poll,1500);else if(j.title)load()}catch(e){timer=setTimeout(poll,3000)}}
async function loadOutputs(){outputs.innerHTML="読み込んでいます…";try{const o=await api("/api/outputs");outputs.innerHTML=o.length?"<table>"+o.map(n=>`<tr><td>${esc(n)}</td><td><button class="btn" data-sheet="${esc(n)}" onclick="start('/api/compare',{sheet:this.dataset.sheet})">比べる</button></td></tr>`).join("")+"</table>":'<div class="empty">出力シートがありません</div>'}catch(e){outputs.innerHTML=`<span class="ng">${esc(e.message)}</span>`}}
async function loadChecks(){checks.innerHTML="確認しています…";try{const c=await api("/api/checks");checks.innerHTML="<table>"+c.map(i=>`<tr><td>${i.ok?'<span class="ok">✔</span>':'<span class="ng">✖</span>'}</td><td>${esc(i.name)}</td><td class="note">${i.ok?"":esc(i.hint)}</td></tr>`).join("")+"</table>"}catch(e){checks.textContent=e.message}}
async function checkUpdate(){ver.textContent="確認しています…";try{const u=await api("/api/update");const c=u.current.updated_at?`今の版：${esc(u.current.message||"")}（${esc(u.current.updated_at)} に更新）`:"今の版：このツールから更新したことがないため不明";ver.innerHTML=`${c}<br>最新の版：${esc(u.latest.message)}（${esc(u.latest.date)}）<br>`+(u.new?'<b class="warn">新しい版があります</b>':'<span class="ok">最新です</span>')}catch(e){ver.innerHTML=`<span class="ng">確認できませんでした：${esc(e.message)}</span>`}}
function showUpdate(r){u_result.innerHTML=`<span class="ok">${r.changed}個のファイルを更新しました。</span>`+(r.pip_ok?"":`<br><span class="ng">部品の入れ直しでエラー：${esc(r.pip)}</span>`)+"<br><b>黒い画面と操作画面を閉じて、app.bat を開き直してください。</b>";checkUpdate()}
u_github.onclick=async()=>{if(!confirm("GitHub から最新の版を取り込みます。よろしいですか？"))return;u_result.textContent="更新しています…";try{showUpdate(await post("/api/update/github",{}))}catch(e){u_result.innerHTML=`<span class="ng">${esc(e.message)}</span>`}};
u_zip_btn.onclick=async()=>{const f=u_zip.files[0];if(!f)return alert("ZIP ファイルを選んでください");u_result.textContent="更新しています…";try{showUpdate(await api("/api/update/zip",{method:"POST",body:await f.arrayBuffer()}))}catch(e){u_result.innerHTML=`<span class="ng">${esc(e.message)}</span>`}};
load();poll();
</script></body></html>
"""

if __name__ == "__main__":
    main()
