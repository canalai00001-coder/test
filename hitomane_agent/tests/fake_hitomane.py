"""テスト用のにせのヒトマネ管理画面（http.server）。

2026-11-16 の画面調査で分かった実物の作りをまねる：募集管理の検索は Ajax（#search_freeword・#search_recruitments・
a.btn_search_btn02）、検索欄の見出しにも「検索」の文字がある、「ファイル取出予約」は export_bg_csv() で確認ダイアログが出る、
予約の一覧は「取込ファイル一覧」（csv_import_queues）と「取出ファイル一覧」（csv_export_queues）に分かれている。
取込ダイアログは iframe（select_new_format）で、#file_csv・#duplicate_check_term・a.btn_operation_btn02（queue_import()）。
取込ファイル一覧の結果の出方（完了・エラーの文言）は実物ではまだ見ていないので、ここでは State で変えられるようにしている。
"""
import csv
import io
import re
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse


class State:
    def __init__(self):
        self.forbidden = False
        self.reserve_link = True
        self.import_reserved = False
        self.export_reserved = 0
        self.saved = False       # 原稿の詳細画面で「保存」が押されたか
        self.code = "CB93208"  # 一覧のいちばん上の原稿の募集番号
        self.last_search = None  # 最後に検索した (フリーワード, 項目)
        self.hits = 1           # 募集管理の検索結果の件数
        self.export_ready_after = 1  # 「最新を表示する」を何回押したら完了になるか（-1 なら完了しない）
        self.refreshes = 0
        self.old_done_row = False  # 前からある「完了」の行を一覧に出すか
        self.export_lost = False   # 取出予約を受け付けても一覧に行が増えない（予約が通らなかったとき）
        self.total = 50000          # 募集管理の全件数
        self.imports = []            # 取り込んだ {"file": bytes, "dup": 「上書きせずに取り込む」が付いていたか}
        self.dup_default = False     # 取込ダイアログの「上書きせずに取り込む」が最初から付いているか
        self.import_ready_after = 2  # 取込ファイル一覧で「最新を表示する」を何回押したら終わるか（-1 なら終わらない。1回目は「進行中」）
        self.import_refreshes = 0
        self.import_status = "完了"
        # 終わった行の詳細。None なら実物（2026-11-16 に1件取り込んだとき）と同じ「成功: N件 （8秒）」（N は CSV の行数）
        self.import_detail = None
        self.csv = "﻿募集番号,ステータス,開始日,終了日\r\nCB93208,掲載,2026/08/17,2027/08/17\r\n"
        # 取り下げのテスト用：募集管理にある原稿（新フォーマットの {列: 値}）。None なら上の csv を取り出す
        self.jobs = None
        self.branches = [("ダミーエリア", "B001", "-", "CB株式会社")]  # 拠点の一覧の行
        self.last_filter = None   # 最後の検索の条件（日付の検索）
        self.export_csv = None    # 取出予約したときの CSV（cp932）


JOBS = """<div class=title>検索</div>
<form id=as_rec_recruitments-search-form onsubmit="return false">フリーワード
<input type=text name=search id=search_freeword>
<select name=search_recruitments id=search_recruitments><option value="">全ての項目</option><option value=m_branch>会社名</option>
<option value=code>募集番号</option></select>
掲載開始日<input id=posted_start_from type=text>
<input type=hidden id=posted_start_from_year name="posted_start_from[year]"><input type=hidden id=posted_start_from_month name="posted_start_from[month]">
<input type=hidden id=posted_start_from_day name="posted_start_from[day]">～<input id=posted_start_to type=text>
<input type=hidden id=posted_start_to_year name="posted_start_to[year]"><input type=hidden id=posted_start_to_month name="posted_start_to[month]">
<input type=hidden id=posted_start_to_day name="posted_start_to[day]">
<input type=checkbox value=1 name="search_condition[posted_only]" id=search_condition_posted_only>掲載のみ
<a href=# class="btn_search_btn01" onclick="return false;">クリア</a>
<a href=# class="btn_search_btn02 hito_enterkey" onclick="doSearch();return false;">検索</a></form>
<div id=as_rec_recruitments-content><div class=count>全{total}件</div>
<table><tr class=record id=as_rec_recruitments-list-573038-row><td>自社</td><td>掲載</td><td>CB株式会社(B001)</td>
<td><a class=btn_list_btn02 title="詳細を開く" href=/m66w/rec_recruitments/edit/573038>詳細</a></td></tr></table></div>
<p>使い方：<a href=/m66w/help>「ファイル取出予約」機能について</a></p>
<a href=# class=btn_menu_btn08 onclick="export_bg_csv();return false;">ファイル取出予約</a>
<a href=/m66w/rec_recruitment_csv_items/select_new_format class="btn_menu_btn08 hito_subwindow"
   onclick="document.getElementById('dlg').style.display='block';document.getElementById('sub').src=this.href;return false;">ファイル取込予約</a>
<div id=dlg style="display:none"><iframe id=sub class=cboxIframe></iframe></div>
<script>
function doSearch() {
  var w = document.getElementById('search_freeword'), f = document.getElementById('search_recruitments');
  var qs = 'search=' + encodeURIComponent(w.value) + '&search_recruitments=' + encodeURIComponent(f.value);
  // 実物と同じく、日付は隠れた欄（年・月・日）が送られる（画面の入力欄は送られない）
  ['posted_start_from', 'posted_start_to'].forEach(function (k) {
    ['year', 'month', 'day'].forEach(function (p) {
      qs += '&' + k + '_' + p + '=' + encodeURIComponent(document.getElementById(k + '_' + p).value);
    });
  });
  if (document.getElementById('search_condition_posted_only').checked) qs += '&posted_only=1';
  w.disabled = true;
  setTimeout(function () {
    fetch('/m66w/rec_recruitments/update_table?' + qs).then(function (r) { return r.text(); }).then(function (t) {
      document.getElementById('as_rec_recruitments-content').innerHTML = t; w.disabled = false;
    });
  }, 300);
}
function export_bg_csv() {
  if (confirm('ファイル取出予約を行いますか？')) {
    fetch('/m66w/export_reserve', {method: 'POST'}).then(function () { alert('ファイル取出予約を受け付けました'); });
  }
}
</script>"""

PAGE = "<!doctype html><html><head><meta charset=utf-8><title>{title}</title></head><body>{body}</body></html>"


def make_handler(st: State):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body="", ctype="text/html; charset=utf-8", location=None, title="HITO-Manager"):
            data = (PAGE.format(title=title, body=body) if ctype.startswith("text/html") else body).encode("utf-8")
            self.send_response(code)
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if st.forbidden:
                return self.send(403, "<h1>403 Forbidden</h1>", title="403 Forbidden")
            if u.path == "/m66w/":
                return self.send(200, "<form method=post action=/m66w/login>ユーザーID<input type=text name=uid>"
                                      "パスワード<input type=password name=pw><button type=submit>ログイン</button></form>")
            if u.path == "/m66w/top":
                links = ("<a href=/m66w/csv_import_queues>取込ファイル一覧</a>"
                         "<a href=/m66w/csv_export_queues>取出ファイル一覧</a>") if st.reserve_link else ""
                return self.send(200, "<h2>募集情報を管理する</h2><a href=/m66w/rec_recruitments>募集管理</a>"
                                      "<button id=imp onclick=\"document.getElementById('dlg').style.display='block'\">ファイルを取込む</button>"
                                      # 実物は、ダイアログの中身を iframe（select_new_format）で表示する
                                      "<div id=dlg style='display:none'><iframe class=cboxIframe "
                                      "src=/m66w/rec_recruitment_csv_items/select_new_format></iframe>"
                                      "<button onclick=\"document.getElementById('dlg').style.display='none'\">閉じる</button></div>" + links)
            if u.path == "/m66w/rec_recruitment_csv_items/select_new_format":
                checked = " checked" if st.dup_default else ""
                return self.send(200, "募集情報のファイルを取り込む（新フォーマット）"
                                      "<form id=rec_form method=post action=/m66w/rec_recruitment_csv_items/complete_new_format "
                                      "enctype=multipart/form-data><input type=hidden name=format_name value=newhmgrfrm>"
                                      "<input id=file_csv name='file[csv]' type=file>"
                                      f"<input type=checkbox name=duplicate_check_term id=duplicate_check_term value=1{checked}>"
                                      "<label for=duplicate_check_term>既存原稿と同じ募集番号の原稿を上書きせずに取り込む</label>"
                                      "<a href=# class=btn_operation_btn02 onclick='queue_import();'>ファイル取込予約</a></form>"
                                      "<script>function queue_import() { if (confirm('ファイル取込予約を行いますか？')) "
                                      "document.getElementById('rec_form').submit(); }</script>")
            if u.path == "/m66w/rec_recruitments":
                return self.send(200, JOBS.replace("{total}", str(st.total)))
            if u.path == "/m66w/rec_recruitments/edit/573038":
                return self.send(200, "<form method=post action=/m66w/rec_recruitments/update/573038><table>"
                                      "<tr><th>媒体</th><td>自社</td></tr>"
                                      f"<tr><th>募集番号<span class=req>必須</span></th><td><input type=text name='record[c01]' value='{st.code}'></td></tr>"
                                      "</table><button type=submit>保存する</button></form>")
            if u.path == "/m66w/rec_recruitments/update_table":
                word, field = q.get("search", [""])[0], q.get("search_recruitments", [""])[0]
                st.last_search = (word, field)
                n = st.hits if word else 50000
                if st.jobs is not None:
                    def day(k):
                        y, m, d = (q.get(f"{k}_{p}", [""])[0] for p in ("year", "month", "day"))
                        return date(int(y), int(m), int(d)) if y else None
                    lo, hi, only = day("posted_start_from"), day("posted_start_to"), bool(q.get("posted_only"))
                    st.last_filter = (lo, hi, only)

                    def hit(j):
                        s = date(*map(int, j["開始日"].split("/")))
                        return ((lo is None or s >= lo) and (hi is None or s <= hi)
                                and (not only or j["ステータス"] == "掲載"))
                    n = sum(1 for j in st.jobs if hit(j))
                    st.export_rows = [j for j in st.jobs if hit(j)]
                return self.send(200, f"<div class=count>全{n}件</div>", ctype="text/plain; charset=utf-8")
            if u.path == "/m66w/m_branches":
                rows = "".join("<tr class=record>" + "".join(f"<td>{c}</td>" for c in b) + "</tr>" for b in st.branches)
                return self.send(200, f"<div>全{len(st.branches)}件</div><table><tbody class=messages><tr><td>見つかりませんでした"
                                      f"</td></tr></tbody><tbody class=records>{rows}</tbody></table>")
            if u.path == "/m66w/csv_import_queues":
                if q.get("refresh"):
                    st.import_refreshes += 1
                done = st.import_ready_after >= 0 and st.import_refreshes >= st.import_ready_after
                rows = ""
                for n, imp in reversed(list(enumerate(st.imports, start=1))):
                    last = n == len(st.imports)
                    finished = done or not last
                    # 実物は 待機中「実行までしばらくお待ち下さい」→ 進行中「0/1件」→ 完了「成功: 1件 （2秒）」
                    lines = len(list(csv.reader(io.StringIO(imp["file"].decode("cp932"), newline="")))) - 1
                    if finished:
                        status = st.import_status
                        detail = st.import_detail if st.import_detail is not None else f"成功: {lines}件 （8秒）"
                    elif st.import_refreshes == 0:
                        status, detail = "待機中", "実行までしばらくお待ち下さい"
                    else:
                        status, detail = "進行中", f"0/{lines}件"
                    rows += (f"<tr class=record><td>2026/11/16 10:00:{n:02d}</td>"
                             f"<td>{'2026/11/16 10:05:00' if finished else '-'}</td><td>募集管理（新）</td>"
                             f"<td>upload_{n}.csv</td><td class=status-column>{status}</td><td>{detail}</td><td>2026/11/19</td></tr>")
                empty = ("<tbody class=messages><tr><td colspan=7><p class=empty-message"
                         f"{' style=display:none' if rows else ''}>見つかりませんでした</p></td></tr></tbody>")
                return self.send(200, "<ul><li>「最新を表示する」ボタンをクリック、または一定時間ごとに画面はリロードされ最新の状況が表示されます</li></ul>"
                                      "<a href='javascript: void(0);' id=view_reload_button title=リロード "
                                      "onclick=\"location.href='/m66w/csv_import_queues?refresh=1'\">最新を表示する</a>"
                                      "<table><tr><th>リクエスト日時</th><th>取込完了日時</th><th>データ種別</th><th>取込ファイル</th>"
                                      "<th>ステータス</th><th>詳細</th><th>削除予定日</th></tr>"
                                      + empty + "<tbody class=records>" + rows + "</tbody></table>")
            if u.path == "/m66w/csv_export_queues":
                if q.get("refresh"):
                    st.refreshes += 1
                done = st.export_ready_after >= 0 and st.refreshes >= st.export_ready_after
                detail = "取出しファイル: <a href=/m66w/dl/sample.csv>rec_jobs_sample.csv</a> 全1件" if done else "実行までしばらくお待ち下さい"
                old = ("<tr class=record><td>2026/11/15 09:00:00</td><td>募集管理（新）</td><td>完了</td>"
                       "<td>取出しファイル: <a href=/m66w/dl/old.csv>rec_jobs_old.csv</a> 全50000件</td></tr>") if st.old_done_row else ""
                mine = (f"<tr class=record><td>2026/11/16 10:00:00</td><td>募集管理（新）</td><td>{'完了' if done else '待機中'}</td>"
                        f"<td>{detail}</td></tr>") if st.export_reserved and not st.export_lost else ""
                # 実物は、件数があっても「見つかりませんでした」の行が tbody.messages に残っている（見えないだけ）
                empty = ("<tbody class=messages><tr><td colspan=5><p class=empty-message"
                         f"{' style=display:none' if (mine or old) else ''}>見つかりませんでした</p></td></tr></tbody>")
                return self.send(200, "<ul><li>「最新を表示する」ボタンをクリック、または一定時間ごとに画面はリロードされ最新の状況が表示されます</li></ul>"
                                      "<a href='javascript: void(0);' id=view_reload_button title=リロード "
                                      "onclick=\"location.href='/m66w/csv_export_queues?refresh=1'\">最新を表示する</a>"
                                      "<table><tr><th>リクエスト日時</th><th>データ種別</th><th>ステータス</th><th>詳細</th></tr>"
                                      + empty + "<tbody class=records>" + mine + old + "</tbody></table>")
            if u.path in ("/m66w/dl/sample.csv", "/m66w/dl/old.csv"):
                self.send_response(200)
                data = st.export_csv if (st.export_csv is not None and u.path.endswith("sample.csv")) else st.csv.encode("utf-8")
                self.send_header("Content-Type", "text/csv")
                self.send_header("Content-Disposition", "attachment; filename=rec_jobs_sample.csv")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            self.send(404, "not found")

        def do_POST(self):
            u = urlparse(self.path)
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            body = raw.decode("utf-8", "replace")
            if u.path == "/m66w/login":
                ok = "pw=pw" in body
                return self.send(302, "", location="/m66w/top" if ok else "/m66w/")
            if u.path.startswith("/m66w/rec_recruitments/update/"):
                st.saved = True
                return self.send(200, "saved")
            if u.path == "/m66w/rec_recruitment_csv_items/complete_new_format":
                boundary = re.search(r"boundary=(.+)", self.headers["Content-Type"]).group(1).encode()
                part = next(p for p in raw.split(b"--" + boundary) if b'name="file[csv]"' in p)
                data = part.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
                st.imports.append({"file": data, "dup": b'name="duplicate_check_term"' in raw})
                st.import_reserved = True
                st.import_refreshes = 0
                # 実物は、予約するとダイアログが閉じて募集管理の画面が読み込み直される（iframe はなくなる）
                return self.send(200, "ファイル取込予約を受け付けました<script>parent.location.reload();</script>")
            if u.path == "/m66w/import_reserve":
                st.import_reserved = True
                return self.send(200, "ok")
            if u.path == "/m66w/export_reserve":
                st.export_reserved += 1
                st.refreshes = 0
                if st.jobs is not None:  # 最後の検索の結果を、実物と同じ形の CSV（cp932）にする
                    from hitomane_agent.checks import Manuscript
                    from hitomane_agent.csv_export import to_csv_bytes
                    from hitomane_agent.headers import NEW_FORMAT
                    rows = getattr(st, "export_rows", st.jobs)
                    st.export_csv = to_csv_bytes(Manuscript("x", [NEW_FORMAT] + [[j[h] for h in NEW_FORMAT] for j in rows]))
                return self.send(200, "ok", ctype="text/plain; charset=utf-8")
            self.send(404, "not found")
    return H


def start():
    st = State()
    srv = HTTPServer(("127.0.0.1", 0), make_handler(st))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, st, f"http://127.0.0.1:{srv.server_port}/m66w/"
