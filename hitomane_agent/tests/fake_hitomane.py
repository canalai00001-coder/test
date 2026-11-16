"""テスト用のにせのヒトマネ管理画面（http.server）。実物の画面の作りは画面調査の結果で分かるので、ここでは文字で探せる形だけをまねる。"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse


class State:
    def __init__(self):
        self.forbidden = False
        self.reserve_link = True
        self.import_reserved = False
        self.export_reserved = 0
        self.hits = 1           # 募集管理の検索結果の件数
        self.export_ready_after = 1  # 「最新を表示する」を何回押したら完了になるか（-1 なら完了しない）
        self.refreshes = 0
        self.csv = "﻿募集番号,ステータス,開始日,終了日\r\nCB93208,掲載,2026/08/17,2027/08/17\r\n"


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
                link = "<a href=/m66w/reservations>ファイル取込・取出予約一覧</a>" if st.reserve_link else ""
                return self.send(200, "<h2>募集情報を管理する</h2><a href=/m66w/jobs>募集管理</a>"
                                      "<button id=imp onclick=\"document.getElementById('dlg').style.display='block'\">ファイルを取込む</button>"
                                      "<div id=dlg style='display:none'>募集情報のファイルを取り込む（新フォーマット）"
                                      "<input type=file name=f><button onclick=\"fetch('/m66w/import_reserve',{method:'POST'})\">ファイル取込予約</button>"
                                      "<button onclick=\"document.getElementById('dlg').style.display='none'\">閉じる</button></div>" + link)
            if u.path == "/m66w/jobs":
                word = q.get("word", [""])[0]
                n = st.hits if word else 50000
                return self.send(200, "<form action=/m66w/jobs>フリーワード<input type=text name=word>"
                                      "<button type=submit>検索</button></form>"
                                      f"<div class=count>全{n}件</div>"
                                      "<form method=post action=/m66w/export_reserve><button type=submit>ファイル取出予約</button></form>"
                                      "<button>ファイル取込予約</button>")
            if u.path == "/m66w/reservations":
                if q.get("refresh"):
                    st.refreshes += 1
                done = st.export_ready_after >= 0 and st.refreshes >= st.export_ready_after
                detail = "取出しファイル: <a href=/m66w/dl/sample.csv>rec_jobs_sample.csv</a> 全1件" if done else "実行までしばらくお待ち下さい"
                return self.send(200, "<a href=/m66w/reservations?refresh=1>最新を表示する</a>"
                                      "<table><tr><th>リクエスト日時</th><th>データ種別</th><th>ステータス</th><th>詳細</th></tr>"
                                      f"<tr><td>2026/11/16 10:00:00</td><td>募集管理（新）</td><td>{'完了' if done else '待機中'}</td>"
                                      f"<td>{detail}</td></tr></table>")
            if u.path == "/m66w/dl/sample.csv":
                self.send_response(200)
                data = st.csv.encode("utf-8")
                self.send_header("Content-Type", "text/csv")
                self.send_header("Content-Disposition", "attachment; filename=rec_jobs_sample.csv")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            self.send(404, "not found")

        def do_POST(self):
            u = urlparse(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)).decode()
            if u.path == "/m66w/login":
                ok = "pw=pw" in body
                return self.send(302, "", location="/m66w/top" if ok else "/m66w/")
            if u.path == "/m66w/import_reserve":
                st.import_reserved = True
                return self.send(200, "ok")
            if u.path == "/m66w/export_reserve":
                st.export_reserved += 1
                st.refreshes = 0
                return self.send(302, "", location="/m66w/reservations")
            self.send(404, "not found")
    return H


def start():
    st = State()
    srv = HTTPServer(("127.0.0.1", 0), make_handler(st))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, st, f"http://127.0.0.1:{srv.server_port}/m66w/"
