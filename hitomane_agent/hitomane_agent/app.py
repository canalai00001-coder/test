"""操作画面。app.bat から起動すると、パソコンの中だけで動く画面がブラウザで開く。

画面からできること
  - 入稿：募集管理の全件数（上限まであと何件か）と、出力シート（ヒトマネ出力_…）の一覧と、チェック・入稿の状態を見る
  - チェック：シートを読んでチェックし、結果（report.html）を開く
  - 入稿ボタン：止める条件と、募集管理の全件数を確かめてから、ヒトマネに取り込む（裏で upload コマンドを動かし、出力を画面に出す）
  - 取り下げ：掲載開始日の期間を入れて「確認だけ」で件数を見てから、「取り下げる」（今日・同じ条件の確認のファイルを使う）
  - 更新：GitHub に新しい版があるかを確かめ、ボタン1つで最新にする（ダウンロードした ZIP からも）
  - 会社：ヒトマネは会社ごとに管理画面の URL が違う（ID・パスワードは同じ）。上の帯で会社を選ぶと、入稿・取り下げはその会社に対して行う。
    会社の一覧はログイン情報シートの会社の行から読む。会社タブで、会社ごとにログインできるかと全件数・拠点を確かめる
  - 設定の確認：鍵・ログインID・スプレッドシート・ログイン情報がそろっているか、ヒトマネにログインできるか

見た目とタブの分け方は Q-mate 版（qmate_agent/qmate_agent/app.py）に合わせている。
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

    # ---- 会社 ----
    def _companies(self) -> list[dict]:
        from . import accounts
        return accounts.companies(self._settings())

    def companies(self) -> list[dict]:
        """会社の一覧と、会社ごとに最後に確かめた全件数（パスワードは含まない）。"""
        limit = config.load("rules.json")["total_limit"]
        out = []
        for c in self._companies():
            t = workflow.last_total(c["code"])
            out.append({**c, "total": t.get("total"), "total_at": t.get("at", ""), "limit": limit,
                        "left": (limit - t["total"]) if t.get("total") is not None else None})
        return out

    def company(self, code) -> dict:
        """画面から来た会社のコードを、ログイン情報シートの会社と照らし合わせる。"""
        if not code:
            raise RuntimeError("会社を選んでください")
        c = next((x for x in self._companies() if x["code"] == code), None)
        if c is None:
            raise RuntimeError(f"会社「{code}」がログイン情報シートにありません。「会社」タブで一覧を読み直してください")
        return c

    def sheets(self, code: str = "") -> list[dict]:
        from .sheet import Spreadsheet

        names = Spreadsheet(self._settings(), self.book).output_sheet_names()
        reviews = workflow.load_state("reviews.json")
        out = []
        for n in names:
            rv, up = reviews.get(n, {}), (workflow.uploaded_entry(code, n) if code else None)
            out.append({"name": n, "status": rv.get("status", ""), "rows": rv.get("rows"),
                        "checked_at": rv.get("checked_at", ""), "uploaded_at": up["uploaded_at"] if up else "",
                        "uploaded_same": bool(up and up.get("hash") == rv.get("hash"))})
        return out

    def check(self, name: str) -> dict:
        ms = workflow.load_manuscript(self._settings(), sheet=name, book=self.book)
        res = workflow.check(ms, config.load("rules.json"))
        return {k: res[k] for k in ("name", "status", "rows", "counts", "sheet_issues")}

    def prepare(self, name: str, code: str, acct=None) -> dict:
        """入稿の前の確認：止める理由、件数、その会社の募集管理の全件数と拠点（ログインして読む）。"""
        c = self.company(code)
        ms = workflow.load_manuscript(self._settings(), sheet=name, book=self.book)
        problem = workflow.upload_problem(ms, code)
        if problem:
            return {"ok": False, "problem": problem}
        rv = workflow.load_state("reviews.json")[name]
        if acct is None:
            from .uploader import HitomaneUploader
            settings = self._settings()
            acct = HitomaneUploader(self._login_info(code), settings["hitomane"], config.OUTPUT_DIR / name).account()
        workflow.save_total(code, acct["total"], c["company"])
        problem = workflow.branch_problem(ms, acct["branches"], c["company"])
        if problem:
            return {"ok": False, "problem": problem}
        return {"ok": True, "rows": len(ms.rows), "status": rv["status"], "company": c["company"],
                "branches": "、".join(f"{b['name']}（{b['code']}）" for b in acct["branches"]),
                "note": workflow.total_note(acct["total"], len(ms.rows), config.load("rules.json"))}

    def upload_args(self, body: dict) -> tuple[str, list[str]]:
        c, name = self.company(body.get("company")), body["name"]
        problem = workflow.upload_problem(workflow.load_manuscript(self._settings(), sheet=name, book=self.book), c["code"])
        if problem:
            raise RuntimeError(problem)
        return f"入稿：{name} → {c['company']}", ["upload", "--sheet", name, "--company", c["code"], "--yes"]

    def login_args(self, body: dict) -> tuple[str, list[str]]:
        if body.get("all"):
            return "全社のログインの確認", ["login", "--all"]
        c = self.company(body.get("company"))
        return f"ログインの確認：{c['company']}", ["login", "--company", c["code"]]

    # ---- 取り下げ ----
    def takedown_args(self, body: dict) -> tuple[str, list[str]]:
        """「確認だけ」はいつでも、「取り下げる」は今日・同じ条件の「確認だけ」があるときだけ。"""
        from datetime import date

        from . import takedown
        c = self.company(body.get("company"))
        cond = takedown.Conditions(takedown.parse_day(body["from"]), takedown.parse_day(body["to"]))
        if cond.start_from > cond.start_to:
            raise ValueError("期間の「から」が「まで」より後です")
        args = ["takedown", "--company", c["code"], "--from", f"{cond.start_from:%Y/%m/%d}",
                "--to", f"{cond.start_to:%Y/%m/%d}"]
        if body.get("prepare_only"):
            return f"取り下げの確認：{c['company']}・{cond.describe()}", args + ["--prepare-only"]
        p = takedown.find_prepared(c["code"], cond, date.today())
        if not p:
            raise RuntimeError("先に、同じ期間で「確認だけ」をしてください（今日のもの）")
        if not p["rows"]:
            raise RuntimeError("取り下げる原稿がありません")
        return f"取り下げ：{c['company']}・{cond.describe()}（{p['rows']}件）", args + ["--yes"]

    def prepared(self, code: str) -> list[dict]:
        from datetime import date

        from . import takedown
        return takedown.prepared_list(date.today(), code)

    def history(self, code: str = "") -> list[dict]:
        """これまでの取り下げ（新しい順）。code があればその会社のものだけ。"""
        p = config.STATE_DIR / "takedown.json"
        rows = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        return [{k: r.get(k) for k in ("at", "company", "login_id", "conditions", "rows", "ok")}
                for r in reversed(rows) if not code or r.get("account") == code]

    # ---- 上の帯・入稿タブ ----
    def overview(self) -> dict:
        from datetime import date

        settings = self._settings()
        return {"today": f"{date.today():%Y/%m/%d}", "login_user": settings.get("login_user") or "",
                "company": settings.get("company") or ""}

    # ---- 設定の確認 ----
    def checks(self) -> list[dict]:
        """ログインまでに要るものがそろっているか。パスワードの中身は返さない。"""
        settings = self._settings()
        items = [{"name": "サービスアカウントの鍵（service_account.json）",
                  "ok": (config.ROOT / settings["service_account_file"]).exists(),
                  "hint": "qmate_agent の service_account.json を hitomane_agent フォルダにも置いてください"},
                 {"name": "このパソコンで使うログインID（login_user）",
                  "ok": bool((settings.get("login_user") or "").strip()),
                  "hint": "config\\settings.local.json に \"login_user\" を書いてください（空欄なら担当者の行の最初の行を使います）"}]
        try:
            from .sheet import Spreadsheet
            n = len(Spreadsheet(settings, self.book).output_sheet_names())
            items.append({"name": f"【AI用】スプレッドシートを読める（出力シート {n}枚）", "ok": True, "hint": ""})
        except Exception as e:
            items.append({"name": "【AI用】スプレッドシートを読める", "ok": False,
                          "hint": f"読めませんでした：{e}（サービスアカウントに共有されているか確かめてください）"})
        try:
            cs = self._companies()
            items.append({"name": f"ヒトマネの会社（{len(cs)}社：{'、'.join(c['company'] for c in cs)}）", "ok": bool(cs),
                          "hint": "ログイン情報シートに、会社名とヒトマネの URL（https://kanri.hitomgr.jp/○○/login）の行を足してください"})
            info = self._login_info(cs[0]["code"] if cs else None)
            items.append({"name": f"ヒトマネのログイン情報（{info['login_id']}）", "ok": True, "hint": ""})
        except Exception as e:
            items.append({"name": "ヒトマネのログイン情報", "ok": False, "hint": str(e)})
        return items

    def _login_info(self, code: str | None = None) -> dict:
        from . import accounts
        return accounts.login_info(self._settings(), company=code)

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

    def update_from_zip(self, data: bytes) -> dict:
        """ダウンロードしておいた GitHub の ZIP から更新する（GitHub に繋がらないとき用）。"""
        changed = apply_zip(data, self._settings()["update"]["subdir"])
        _save_version({"sha": "", "date": "", "message": "ダウンロードした ZIP から更新",
                       "updated_at": datetime.now().isoformat(timespec="seconds")})
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


PAGE = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ヒトマネ入稿ツール</title>
<style>
:root{--bg:#f5f6f8;--card:#fff;--ink:#1f2328;--sub:#59636e;--line:#d8dde3;--accent:#1f6feb;--danger:#cf222e;--ok:#1a7f37;--warn:#9a6700}
*{box-sizing:border-box}body{margin:0;font-family:"Yu Gothic UI","Meiryo",sans-serif;background:var(--bg);color:var(--ink);font-size:14px}
header{background:#24292f;color:#fff;padding:12px 20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
header h1{font-size:16px;margin:0;font-weight:600}header span{color:#aab3bd;font-size:12px}
header .co{margin-left:auto;display:flex;flex-direction:row;align-items:center;gap:8px;color:#fff;font-size:13px}
header select{padding:5px 8px;border-radius:6px;border:1px solid #57606a;background:#fff;color:var(--ink);font-size:13px;min-width:220px;max-width:100%}
nav{display:flex;gap:4px;padding:0 20px;background:#fff;border-bottom:1px solid var(--line);overflow-x:auto}
nav button{border:0;background:none;padding:12px 16px;font-size:14px;cursor:pointer;color:var(--sub);border-bottom:2px solid transparent;white-space:nowrap}
nav button.on{color:var(--ink);border-bottom-color:var(--accent);font-weight:600}
main{padding:20px;max-width:1200px;margin:0 auto}section{display:none}section.on{display:block}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;margin-bottom:16px}
.card h2{font-size:15px;margin:0 0 12px}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}th{color:var(--sub);font-weight:600;background:#fafbfc}
.btn{border:1px solid var(--line);background:#fff;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:13px;white-space:nowrap}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}.btn.danger{background:var(--danger);border-color:var(--danger);color:#fff}
.btn:disabled{opacity:.5;cursor:not-allowed}.row{display:flex;gap:12px;flex-wrap:wrap;align-items:end;margin-bottom:12px}
label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--sub)}input{padding:6px 8px;border:1px solid var(--line);border-radius:6px;font-size:13px}
pre{background:#0d1117;color:#e6edf3;padding:12px;border-radius:8px;height:320px;overflow:auto;font-size:12px;white-space:pre-wrap;margin:0}
.note{color:var(--sub);font-size:12px;margin:4px 0 0}.card>p.note{margin-bottom:12px}.ok,.OK{color:var(--ok)}.ng,.NG{color:var(--danger)}.warn,.要確認{color:var(--warn)}
.OK,.NG,.要確認{font-weight:600}.status{font-size:13px;margin-bottom:8px}.empty{color:var(--sub);padding:12px 0}.big{font-size:20px;font-weight:600}
.coname{display:inline-block;background:#ddf4ff;color:#0969da;border-radius:12px;padding:1px 10px;font-weight:600;font-size:13px}
</style></head><body>
<header><h1>ヒトマネ入稿ツール</h1><span id="today"></span><span id="who"></span>
  <label class="co">会社<select id="company"><option value="">読み込んでいます…</option></select></label></header>
<nav><button data-tab="post" class="on">入稿</button><button data-tab="takedown">取り下げ</button><button data-tab="companies">会社</button><button data-tab="update">更新</button><button data-tab="check">設定の確認</button></nav>
<main>
<section id="post" class="on">
  <div class="card"><h2>募集管理の全件数 <span class="coname co_name"></span></h2>
    <div id="total" class="status">読み込んでいます…</div>
    <div class="row"><button class="btn" onclick="loginCo()">ログインして全件数を確かめる</button></div>
    <p class="note">ヒトマネに入れられるのは、会社ごとに 50,000件までです。入稿の前にも、そのときの全件数を読んで確かめます。</p></div>
  <div class="card"><h2>出力シート</h2>
    <p class="note">【AI用】ヒトマネ 求人原稿自動生成 の「ヒトマネ出力_…」シートです。チェックしてから、上で選んだ会社に入稿します。チェックのあとにシートを直したときは、もう一度チェックしてください。<br>
    入稿の前に、シートの拠点コードがその会社の拠点にあるかを確かめます（会社の選び間違いのときは止まります）。</p>
    <div id="sheets">読み込んでいます…</div>
    <div class="row" style="margin-top:12px"><button class="btn" onclick="loadSheets()">一覧を読み直す</button></div></div>
</section>
<section id="takedown">
  <div class="card"><h2>原稿の取り下げ <span class="coname co_name"></span></h2>
    <p class="note">上で選んだ会社の、掲載開始日がこの期間の掲載中の原稿を取り下げます（開始日・終了日を2年前、ステータスを非掲載にして取り込み直します）。<br>
    先に「確認だけ」で件数を見てから、「取り下げる」を押してください。「取り下げる」は、今日・同じ会社・同じ期間の「確認だけ」のファイルを使います。</p>
    <div class="row"><label>掲載開始日（から）<input id="t_from" placeholder="2026/10/01" size="12"></label>
      <label>掲載開始日（まで）<input id="t_to" placeholder="2026/10/31" size="12"></label></div>
    <div class="row"><button class="btn" id="t_dry">確認だけ（ヒトマネは変えない）</button><button class="btn danger" id="t_run">取り下げる</button></div></div>
  <div class="card"><h2>今日の確認 <span class="coname co_name"></span></h2><div id="prepared">読み込んでいます…</div></div>
  <div class="card"><h2>取り下げの記録 <span class="coname co_name"></span></h2><div id="t_history">読み込んでいます…</div></div>
</section>
<section id="companies">
  <div class="card"><h2>ヒトマネの会社</h2>
    <p class="note">ヒトマネは会社ごとに管理画面の URL が違います（ログインID・パスワードはどの会社も同じ）。この一覧は、通勤用スプレッドシートの「ヒトマネログイン情報」シートの、会社名とヒトマネの URL（https://kanri.hitomgr.jp/○○/login）の入った行から読みます。会社を足すときはシートに行を足して「一覧を読み直す」を押してください。</p>
    <div id="co_list">読み込んでいます…</div>
    <div class="row" style="margin-top:12px"><button class="btn primary" onclick="start('/api/login',{all:true})">全社まとめてログインを確かめる</button><button class="btn" onclick="loadCompanies()">一覧を読み直す</button></div>
    <p class="note">ログインの確認は、ブラウザを裏で開いてログインし、募集管理の全件数と拠点を読むだけです。ヒトマネの原稿は変えません。</p></div>
</section>
<section id="update">
  <div class="card"><h2>ツールの更新</h2><div id="ver" class="status">確認しています…</div>
    <div class="row"><button class="btn primary" id="u_github">GitHub から最新にする</button><button class="btn" onclick="checkUpdate()">新しい版があるか確認</button></div>
    <p class="note">ダウンロード済みの ZIP から更新する：<input type="file" id="u_zip" accept=".zip"> <button class="btn" id="u_zip_btn">この ZIP で更新</button></p>
    <p class="note">settings.local.json・service_account.json・.venv・実行記録（state）・出力（output）は上書きしません。更新が終わったら、黒い画面と操作画面を閉じて app.bat を開き直してください。</p>
    <div id="u_result" class="status"></div></div>
</section>
<section id="check">
  <div class="card"><h2>設定の確認</h2><div id="checks"></div>
    <div class="row" style="margin-top:12px"><button class="btn" onclick="loadChecks()">確認し直す</button><button class="btn primary" onclick="loginCo()">選んでいる会社にログインできるか確かめる</button></div>
    <p class="note">ログインの確認は、ブラウザを裏で開いてログインし、募集管理の全件数と拠点を読むだけです。ヒトマネの原稿は変えません。</p></div>
</section>
<div class="card"><h2 id="job_title">実行の記録</h2><div id="job_state" class="status"></div><pre id="log"></pre></div>
</main>
<script>
const T="__TOKEN__";
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const q=p=>p+(p.includes("?")?"&":"?")+"t="+T;
async function api(p,opt){const r=await fetch(q(p),opt);const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j}
const post=(p,b)=>api(p,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});
const num=n=>n==null?"":Number(n).toLocaleString();
const when=s=>esc(String(s||"").replace("T"," "));
let COS=[];
const CO=()=>company.value;
const coName=()=>(COS.find(c=>c.code===CO())||{}).company||"";
const withCo=p=>p+(p.includes("?")?"&":"?")+"company="+encodeURIComponent(CO());
const needCo=()=>{if(!CO()){alert("上の「会社」で会社を選んでください");return false}return true};
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{document.querySelectorAll("nav button,section").forEach(x=>x.classList.remove("on"));b.classList.add("on");document.getElementById(b.dataset.tab).classList.add("on");
  if(b.dataset.tab==="check")loadChecks();if(b.dataset.tab==="update")checkUpdate();if(b.dataset.tab==="takedown")loadTakedown();if(b.dataset.tab==="companies")loadCompanies()});

function showCompanies(){const cur=CO();let saved="";try{saved=localStorage.getItem("company")||""}catch(e){}
  company.innerHTML=COS.length?'<option value="">会社を選んでください</option>'+COS.map(c=>`<option value="${esc(c.code)}">${esc(c.company)}（${esc(c.code)}）</option>`).join(""):'<option value="">会社がありません（会社タブを見てください）</option>';
  const want=[cur,saved,DEFAULT_CO].find(v=>v&&COS.some(c=>c.code===v||c.company===v));const hit=COS.find(c=>c.code===want||c.company===want);
  company.value=hit?hit.code:(COS.length===1?COS[0].code:"");
  co_list.innerHTML=COS.length?"<table><tr><th>会社</th><th>コード</th><th>管理画面</th><th>全件数（最後に確かめたとき）</th><th></th></tr>"+COS.map(c=>`<tr><td>${esc(c.company)}</td><td>${esc(c.code)}</td><td><a href="${esc(c.url)}" target="_blank">${esc(c.url)}</a></td>
   <td>${c.total==null?'<span class="note">まだ確かめていません</span>':`${num(c.total)}件・<b class="${c.left<=0?"ng":c.left<5000?"warn":"ok"}">あと ${num(c.left)}件</b> <span class="note">${when(c.total_at)}</span>`}</td>
   <td><button class="btn" data-c="${esc(c.code)}" onclick="start('/api/login',{company:this.dataset.c})">ログインを確かめる</button></td></tr>`).join("")+"</table>"
   :'<div class="empty">ログイン情報シートに会社の行がありません</div>'}
async function loadCompanies(){co_list.textContent="読み込んでいます…";try{COS=await api("/api/companies");showCompanies();coChanged(false)}catch(e){co_list.innerHTML=`<span class="ng">${esc(e.message)}</span>`;company.innerHTML='<option value="">会社の一覧を読めませんでした</option>'}}
function coChanged(save=true){if(save){try{localStorage.setItem("company",CO())}catch(e){}}
  document.querySelectorAll(".co_name").forEach(x=>{x.textContent=coName();x.style.display=CO()?"":"none"});showTotal();loadSheets();loadTakedown()}
company.onchange=()=>coChanged(true);

let DEFAULT_CO="";
async function loadOverview(){try{const d=await api("/api/overview");today.textContent="今日："+d.today;who.textContent=d.login_user?"ログインID："+d.login_user:"";DEFAULT_CO=d.company||""}catch(e){}}
function showTotal(){const c=COS.find(x=>x.code===CO());
  total.innerHTML=!c?'<span class="note">上の「会社」で会社を選んでください</span>':c.total==null?'<span class="note">まだ確かめていません。「ログインして全件数を確かめる」を押してください</span>':
   `<span class="big">${num(c.total)}件</span>　上限 ${num(c.limit)}件・<b class="${c.left<=0?"ng":c.left<5000?"warn":"ok"}">あと ${num(c.left)}件</b><div class="note">${when(c.total_at)} に確かめた件数です</div>`}
function loginCo(){if(needCo())start("/api/login",{company:CO()})}
async function loadSheets(){sheets.textContent="読み込んでいます…";try{const l=await api(withCo("/api/sheets"));
  sheets.innerHTML=l.length?`<table><tr><th>シート</th><th>原稿</th><th>チェック</th><th>入稿${coName()?"（"+esc(coName())+"）":""}</th><th></th></tr>`+l.map(s=>`<tr><td>${esc(s.name)}</td><td>${s.rows==null?"":num(s.rows)+"件"}</td>
   <td><span class="${esc(s.status)}">${esc(s.status||"未チェック")}</span> <span class="note">${when(s.checked_at)}</span>${s.status?` <a href="${q("/report?name="+encodeURIComponent(s.name))}" target="_blank">結果を見る</a>`:""}</td>
   <td>${s.uploaded_same?'<span class="ok">入稿済み</span> ':""}<span class="note">${when(s.uploaded_at)}</span></td>
   <td><button class="btn" data-n="${esc(s.name)}" onclick="check(this.dataset.n,this)">チェック</button> <button class="btn primary" data-n="${esc(s.name)}" onclick="upload(this.dataset.n,this)" ${CO()&&s.status&&s.status!=="NG"&&!s.uploaded_same?"":"disabled"}>入稿</button></td></tr>`).join("")+"</table>"
   :'<div class="empty">出力シートがありません。GAS の③で原稿を作ってください</div>'}catch(e){sheets.innerHTML=`<span class="ng">一覧を読めませんでした：${esc(e.message)}</span>`}}
async function check(name,b){b.disabled=true;b.textContent="チェック中…";try{const r=await post("/api/check",{name});await loadSheets();
  if(r.status==="NG")alert(`${name}：NG です（原稿 ${r.rows}件）。「結果を見る」で指摘を確かめてください`)}catch(e){alert("チェックできませんでした："+e.message);loadSheets()}}
async function upload(name,b){if(!needCo())return;const co=CO();b.disabled=true;b.textContent="確認中…";
  try{const r=await post("/api/prepare",{name,company:co});if(!r.ok){alert("入稿しません："+r.problem);return}
   const msg=`【${r.company}】に ${name} を取り込みます。\n\n入れる会社：${r.company}（拠点：${r.branches}）\n原稿 ${num(r.rows)}件（チェック ${r.status}）\n${r.note}`+(r.status==="要確認"?"\n\n注意の指摘があります。チェック結果を確かめましたか？":"")+"\n\n会社が合っているか確かめてください。取り込みますか？";
   await start("/api/upload",{name,company:co},msg)}catch(e){alert("確認できませんでした："+e.message)}finally{loadSheets();loadCompanies()}}

const tBody=()=>({from:t_from.value.trim(),to:t_to.value.trim(),company:CO()});
t_dry.onclick=()=>{if(!needCo())return;const b=tBody();if(!b.from||!b.to)return alert("掲載開始日の期間を入れてください");start("/api/takedown",{...b,prepare_only:true})};
t_run.onclick=async()=>{if(!needCo())return;const b=tBody();if(!b.from||!b.to)return alert("掲載開始日の期間を入れてください");
  try{const p=await post("/api/takedown",{...b,preview:true});
   await start("/api/takedown",b,`${p.title}\n\n【${coName()}】の原稿の開始日・終了日を2年前、ステータスを非掲載にして取り込み直します。\n会社と「今日の確認」の件数を確かめましたか？取り下げますか？`)}catch(e){alert(e.message)}};
function useRange(f,t){t_from.value=f;t_to.value=t;t_from.scrollIntoView({behavior:"smooth",block:"center"})}
async function loadTakedown(){if(!CO()){prepared.innerHTML=t_history.innerHTML='<div class="empty">上の「会社」で会社を選んでください</div>';return}
  try{const l=await api(withCo("/api/takedown/prepared"));
  prepared.innerHTML=l.length?"<table><tr><th>条件</th><th>検索の件数</th><th>取り下げる原稿</th><th>除いた原稿</th><th>確認した時刻</th><th></th></tr>"+l.map(p=>`<tr><td>${esc(p.conditions)}</td><td>${num(p.searched)}件</td><td><b>${num(p.rows)}件</b></td>
   <td>${esc(Object.entries(p.skipped||{}).map(([k,v])=>k+" "+num(v)+"件").join("、"))}</td><td>${when(p.prepared_at)}</td>
   <td><button class="btn" data-f="${esc(p.from)}" data-t="${esc(p.to)}" onclick="useRange(this.dataset.f,this.dataset.t)">この期間を入れる</button></td></tr>`).join("")+"</table>"
   :'<div class="empty">この会社では、今日はまだ「確認だけ」をしていません</div>'}catch(e){prepared.innerHTML=`<span class="ng">${esc(e.message)}</span>`}
  try{const h=await api(withCo("/api/takedown/history"));
  t_history.innerHTML=h.length?"<table><tr><th>実行した時刻</th><th>ログインID</th><th>条件</th><th>件数</th><th>結果</th></tr>"+h.map(r=>`<tr><td>${when(r.at)}</td><td>${esc(r.login_id)}</td><td>${esc(r.conditions)}</td><td>${num(r.rows)}件</td>
   <td>${r.ok?'<span class="ok">取り下げました</span>':'<span class="ng">途中で止まりました</span>'}</td></tr>`).join("")+"</table>"
   :'<div class="empty">この会社では、まだ取り下げたことはありません</div>'}catch(e){t_history.innerHTML=`<span class="ng">${esc(e.message)}</span>`}}

async function loadChecks(){checks.textContent="確認しています…";try{const c=await api("/api/checks");checks.innerHTML="<table>"+c.map(i=>`<tr><td style="width:24px">${i.ok?'<span class="ok">✔</span>':'<span class="ng">✖</span>'}</td><td>${esc(i.name)}</td><td class="note">${i.ok?"":esc(i.hint)}</td></tr>`).join("")+"</table>"}catch(e){checks.innerHTML=`<span class="ng">${esc(e.message)}</span>`}}
async function checkUpdate(){ver.textContent="確認しています…";try{const u=await api("/api/update");const c=u.current.updated_at?`今の版：${esc(u.current.message||"")}（${when(u.current.updated_at)} に更新）`:"今の版：このツールから更新したことがないため不明";
  ver.innerHTML=`${c}<br>最新の版：${esc(u.latest.message)}（${when(u.latest.date)}）<br>`+(u.new?'<b class="warn">新しい版があります</b>':'<span class="ok">最新です</span>')}catch(e){ver.innerHTML=`<span class="ng">確認できませんでした：${esc(e.message)}</span>`}}
const showUpdate=r=>{u_result.innerHTML=`<span class="ok">${r.changed}ファイルを更新しました。</span>黒い画面と操作画面を閉じて、app.bat を開き直してください`};
u_github.onclick=async()=>{if(!confirm("GitHub から最新の版を取り込みます。よろしいですか？"))return;u_result.textContent="更新しています…";try{showUpdate(await post("/api/update/github",{}))}catch(e){u_result.innerHTML=`<span class="ng">${esc(e.message)}</span>`}};
u_zip_btn.onclick=async()=>{const f=u_zip.files[0];if(!f)return alert("ZIP ファイルを選んでください");u_result.textContent="更新しています…";try{showUpdate(await api("/api/update/zip",{method:"POST",body:await f.arrayBuffer()}))}catch(e){u_result.innerHTML=`<span class="ng">${esc(e.message)}</span>`}};

let since=0,timer;
async function start(p,b,msg){if(msg&&!confirm(msg))return;try{await post(p,b);since=0;log.textContent="";poll();document.getElementById("job_title").scrollIntoView({behavior:"smooth"})}catch(e){alert(e.message)}}
async function poll(){clearTimeout(timer);try{const j=await api("/api/job?since="+since);if(j.title)job_title.textContent="実行の記録："+j.title;
  if(j.lines.length){log.textContent+=j.lines.join("\n")+"\n";log.scrollTop=log.scrollHeight}since=j.next??since;
  job_state.innerHTML=j.running?'<span class="warn">実行中…（この画面を閉じても止まりませんが、黒い画面は閉じないでください）</span>':(j.code===0?'<span class="ok">終わりました</span>':j.code==null?"":`<span class="ng">止まりました（コード ${j.code}）。記録を確認してください</span>`);
  if(j.running)timer=setTimeout(poll,1500);else if(j.title)loadCompanies()}catch(e){timer=setTimeout(poll,3000)}}
loadOverview().then(loadCompanies);poll();
</script></body></html>
"""


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
                company = q.get("company", [""])[0]
                if u.path == "/api/sheets":
                    return self._send(200, app.sheets(company))
                if u.path == "/api/companies":
                    return self._send(200, app.companies())
                if u.path == "/api/job":
                    since = int(q.get("since", ["0"])[0])
                    return self._send(200, app.job.to_dict(since) if app.job else {"lines": [], "running": False})
                if u.path == "/report":
                    return self._send(200, app.report(q.get("name", [""])[0]), "text/html; charset=utf-8")
                if u.path == "/api/update":
                    return self._send(200, app.update_info())
                if u.path == "/api/takedown/prepared":
                    return self._send(200, app.prepared(company))
                if u.path == "/api/takedown/history":
                    return self._send(200, app.history(company))
                if u.path == "/api/overview":
                    return self._send(200, app.overview())
                if u.path == "/api/checks":
                    return self._send(200, app.checks())
                if u.path == "/api/version":
                    return self._send(200, _version())
            except Exception as e:
                return self._send(500, {"error": html.escape(str(e))})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            u = urlparse(self.path)
            if not self._authorized(parse_qs(u.query)):
                return self._send(403, {"error": "この画面は app.bat から開いてください"})
            try:
                data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if u.path == "/api/update/zip":
                    return self._send(200, app.update_from_zip(data))
                body = json.loads(data or b"{}")
                if u.path == "/api/login":
                    return self._send(200, app.run(*app.login_args(body)))
                if u.path == "/api/check":
                    return self._send(200, app.check(body["name"]))
                if u.path == "/api/prepare":
                    return self._send(200, app.prepare(body["name"], body.get("company")))
                if u.path == "/api/upload":
                    return self._send(200, app.run(*app.upload_args(body)))
                if u.path == "/api/takedown":
                    title, args = app.takedown_args(body)
                    if body.get("preview"):  # 「取り下げる」の確認の文に件数を出すため、実行せずに中身だけ返す
                        return self._send(200, {"title": title})
                    return self._send(200, app.run(title, args))
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
