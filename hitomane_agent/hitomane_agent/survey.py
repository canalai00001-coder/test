"""ヒトマネ管理画面の画面調査。

管理画面は決まったネットワークからしか開けず、作る側からは画面を見られない。そこで、利用者のパソコンでログインして
各画面の HTML・スクリーンショット・リンク一覧を output に保存し、その結果を見てボタンの押し方や CSV の形を決める。

押すのは、ログイン、画面の移動、ダイアログを開く・閉じる、検索だけ。取り込み・取り下げ・掲載状態の変更はしない。
sample（募集番号）を渡したときだけ、その1件を「ファイル取出予約」して、取出ファイル一覧から CSV の見本をダウンロードする。
予約の結果は「取込ファイル一覧」（csv_import_queues）と「取出ファイル一覧」（csv_export_queues）に出る（2026-11-16 の画面調査で確認）。
"""
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import Page, sync_playwright



def _launch(p, headed: bool):
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
    return p.chromium.launch(headless=not headed, executable_path=exe) if exe else p.chromium.launch(headless=not headed)


def _links(page: Page) -> list:
    try:
        pairs = page.eval_on_selector_all(
            "a[href], button, input[type=button], input[type=submit]",
            "els => els.map(e => [(e.innerText || e.value || '').trim().replace(/\\s+/g, ' ').slice(0, 60),"
            " e.getAttribute('href') || ('<' + e.tagName.toLowerCase() + '>')])")
    except Exception:
        return []
    return [(t, h) for t, h in pairs if t or h]


class Survey:
    def __init__(self, info: dict, out_dir: Path, log=print, poll_interval_ms: int = 5000, export_poll_times: int = 360,
                 timeout_ms: int = 60000):
        self.info, self.out, self.log = info, Path(out_dir), log
        self.poll_interval = poll_interval_ms / 1000
        self.export_poll_times = export_poll_times
        self.timeout_ms = timeout_ms
        self.steps = []
        self.export_top = None  # 取り出し予約の前に、取出ファイル一覧のいちばん上にあった行のリクエスト日時
        self.out.mkdir(parents=True, exist_ok=True)

    # ---- 記録 ----
    def save(self, name: str, page: Page) -> None:
        try:
            (self.out / f"{name}.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(self.out / f"{name}.png"), full_page=True)
            (self.out / f"{name}_links.txt").write_text(
                "\n".join(f"{t} → {h}" for t, h in _links(page)), encoding="utf-8")
        except Exception as e:
            self.log(f"  （{name} の保存に失敗しました: {e}）")

    def record(self, name: str, ok: bool, page: Page | None, note: str = "") -> bool:
        self.steps.append({"name": name, "ok": ok, "url": page.url if page else "", "note": note})
        self.log(f"{'○' if ok else '×'} {name}{'：' + note if note else ''}")
        return ok

    def finish(self) -> dict:
        lines = [f"{s['name']}\t{'ok' if s['ok'] else 'NG'}\t{s['url']}\t{s['note']}" for s in self.steps]
        (self.out / "調査結果.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"steps": self.steps, "dir": str(self.out)}

    # ---- 画面ごと ----
    def login(self, page: Page) -> bool:
        name = "01_ログイン画面"
        resp = page.goto(self.info["url"])
        self.save(name, page)
        if resp is not None and resp.status == 403:
            return self.record(name, False, page, "管理画面を開けませんでした（403）。社内のネットワークから実行してください")
        pw = page.locator("input[type=password]")
        if not pw.count():
            return self.record(name, False, page, "パスワードの入力欄が見つかりませんでした")
        user = page.locator("input[type=text], input[type=email], input:not([type])")
        if not user.count():
            return self.record(name, False, page, "ユーザーIDの入力欄が見つかりませんでした")
        user.first.fill(self.info["login_id"])
        pw.first.fill(self.info["password"])
        button = page.locator("button[type=submit], input[type=submit]")
        if not button.count():
            button = page.get_by_role("button", name="ログイン")
        button.first.click()
        page.wait_for_load_state("networkidle")
        if page.locator("input[type=password]").count():
            self.save(name + "_ログイン後", page)
            return self.record(name, False, page, "ログインできませんでした（ID・パスワードを確かめてください）")
        return self.record(name, True, page)

    def click_text(self, page: Page, text: str) -> bool:
        """ボタン・リンクのうち、名前がちょうど text のものを押す。無ければ文字を含むもの。
        （「『ファイル取出予約』機能について」のような説明のリンクを押さないように、ちょうど一致を先に見る）"""
        loc = page.get_by_role("button", name=text, exact=True)
        if not loc.count():
            loc = page.get_by_role("link", name=text, exact=True)
        if not loc.count():
            loc = page.get_by_text(text, exact=True)
        if not loc.count():
            loc = page.get_by_text(text, exact=False)
        if not loc.count():
            return False
        loc.first.click()
        page.wait_for_load_state("networkidle")
        return True

    def run(self, headed: bool = False, sample: str = "") -> dict:
        with sync_playwright() as p:
            browser = _launch(p, headed)
            page = browser.new_context(accept_downloads=True).new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                if not self.login(page):
                    return self.finish()
                top_url = page.url
                self.save("02_トップ", page)
                self.record("02_トップ", True, page)
                top_links = _links(page)
                self.step_import_dialog(page, top_url)
                self.step_old_import(page, top_url)
                jobs_links = self.step_jobs(page, top_url)
                links = top_links + jobs_links
                self.step_queue(page, links, "05_取込ファイル一覧", "取込ファイル一覧")
                export_url = self.step_queue(page, links, "06_取出ファイル一覧", "取出ファイル一覧")
                if sample:
                    self.step_sample(page, sample, top_url, export_url)
            finally:
                browser.close()
        return self.finish()

    def step_import_dialog(self, page: Page, top_url: str) -> None:
        name = "03_ファイル取込ダイアログ"
        try:
            page.goto(top_url)
            if not self.click_text(page, "ファイルを取込む"):
                self.save(name, page)
                self.record(name, False, page, "「ファイルを取込む」が見つかりませんでした")
                return
            page.wait_for_timeout(1000)
            self.save(name, page)
            # ダイアログの中身（ファイル選択欄・取込予約のボタン）は iframe の別ページなので、その HTML も保存する。読むだけで押さない
            inner = next((f for f in page.frames if "csv_items" in f.url or "select_new_format" in f.url), None)
            if inner is not None:
                inner.wait_for_load_state()
                (self.out / f"{name}_中身.html").write_text(inner.content(), encoding="utf-8")
            self.record(name, True, page, "" if inner is not None else "ダイアログの中身（iframe）は見つかりませんでした")
            close = page.get_by_text("閉じる", exact=True)
            if close.count() and close.first.is_visible():
                close.first.click()
        except Exception as e:
            self.record(name, False, page, f"エラー: {e}")

    def step_old_import(self, page: Page, top_url: str) -> None:
        """「旧原稿形式CSV取込」（新原稿形式移行期間中CSV取込）のダイアログを開いて保存する。読むだけで、中のボタンは押さない。"""
        name = "03b_旧原稿形式CSV取込"
        try:
            page.goto(top_url)
            link = page.locator("a[href*='old_import']")
            if not link.count():
                self.save(name, page)
                self.record(name, False, page, "「旧原稿形式CSV取込」のリンクが見つかりませんでした")
                return
            href = link.first.get_attribute("href") or ""
            link.first.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)
            self.save(name, page)
            inner = next((f for f in page.frames if "old_import" in f.url or "migration" in f.url), None)
            if inner is not None:
                inner.wait_for_load_state()
                (self.out / f"{name}_中身.html").write_text(inner.content(), encoding="utf-8")
                (self.out / f"{name}_中身_links.txt").write_text(
                    "\n".join(f"{x} → {h}" for x, h in _links(inner)), encoding="utf-8")
            self.record(name, True, page, f"リンク {href}" + ("" if inner is not None else "（中身の iframe は見つかりませんでした）"))
            close = page.get_by_text("閉じる", exact=True)
            if close.count() and close.first.is_visible():
                close.first.click()
        except Exception as e:
            self.record(name, False, page, f"エラー: {e}")

    def step_jobs(self, page: Page, top_url: str) -> list:
        name = "04_募集管理"
        try:
            page.goto(top_url)
            if not self.click_text(page, "募集管理"):
                self.save(name, page)
                self.record(name, False, page, "「募集管理」が見つかりませんでした")
                return []
            self.save(name, page)
            self.record(name, True, page)
            return _links(page)
        except Exception as e:
            self.record(name, False, page, f"エラー: {e}")
            return []

    def step_queue(self, page: Page, links: list, name: str, title: str) -> str:
        """「取込ファイル一覧」「取出ファイル一覧」（予約の結果が並ぶ画面）を開いて保存する。開いた URL を返す。"""
        try:
            href = next((h for t, h in links if t.strip() == title and h and not h.startswith(("<", "#"))), None)
            if href is None:
                self.record(name, False, page, f"「{title}」へのリンクが見つかりませんでした")
                return ""
            page.goto(urljoin(page.url, href))
            page.wait_for_load_state("networkidle")
            self.save(name, page)
            self.record(name, True, page)
            if title == "取出ファイル一覧":
                self.export_top = self._top_key(page)
            return page.url
        except Exception as e:
            self.record(name, False, page, f"エラー: {e}")
            return ""

    @staticmethod
    def _top_row(page: Page):
        # 一覧の行は tbody.records の tr.record。表の先頭には「見つかりませんでした」の行（tbody.messages）が
        # 件数があっても見えない状態で残っているので、それを行として見ない
        rows = page.locator("tbody.records tr.record")
        if rows.count():
            return rows.first
        return page.locator("tbody.records tr", has=page.locator("td")).first

    def _top_key(self, page: Page) -> str:
        """いちばん上の行の最初の列（リクエスト日時）。行がなければ空。"""
        row = self._top_row(page)
        return row.locator("td").first.inner_text().strip() if row.count() else ""

    def _count(self, page: Page) -> int | None:
        m = re.search(r"全\s*([\d,]+)\s*件", page.inner_text("body"))
        return int(m.group(1).replace(",", "")) if m else None

    def search_code(self, page: Page, code: str) -> int | None:
        """募集管理で、項目「募集番号」・フリーワード code で検索し、件数を返す。
        検索は Ajax で一覧だけ入れ替わる（ページは移らない）ので、件数の表示が変わるか入力欄が使えるようになるまで待つ。"""
        box = page.locator("#search_freeword")
        if not box.count():
            return None
        box.fill(code)
        field = page.locator("#search_recruitments")
        if field.count():
            field.select_option("code")
        before = self._count(page)
        # 検索欄の見出しにも「検索」の文字があるので、文字ではなくボタンの class で押す
        button = page.locator("a.btn_search_btn02")
        if not button.count():
            button = page.get_by_role("link", name="検索", exact=True)
        button.first.click()
        deadline = time.time() + self.timeout_ms / 1000
        while time.time() < deadline:
            page.wait_for_timeout(500)
            if box.is_enabled() and self._count(page) != before:
                break
        page.wait_for_load_state("networkidle")
        return self._count(page)

    def pick_code(self, page: Page) -> str:
        """募集管理の一覧のいちばん上の原稿の「詳細を開く」を開き、募集番号を読む（一覧には募集番号の列がない）。
        詳細画面は読むだけで、保存などのボタンは押さない。"""
        name = "07_見本の原稿"
        link = page.locator("a.btn_list_btn02[href*='/edit/']")
        if not link.count():
            link = page.locator("a[title='詳細を開く']")
        if not link.count():
            self.save(name, page)
            self.record(name, False, page, "一覧に「詳細を開く」が見つかりませんでした（--sample 募集番号 で指定してください）")
            return ""
        page.goto(urljoin(page.url, link.first.get_attribute("href")))
        page.wait_for_load_state("networkidle")
        self.save(name, page)
        code = page.evaluate("""() => {
            const named = document.querySelector("input[name$='[code]']");
            if (named && named.value.trim()) return named.value.trim();
            for (const h of document.querySelectorAll('th, label, dt')) {
                if (!h.textContent.trim().startsWith('募集番号')) continue;
                const box = h.closest('tr') || h.parentElement;
                const input = box && box.querySelector('input[type=text], input:not([type])');
                if (input && input.value.trim()) return input.value.trim();
                const cell = h.nextElementSibling;
                if (cell && cell.textContent.trim()) return cell.textContent.trim().split(/\s+/)[0];
            }
            return '';
        }""")
        if not code:
            self.record(name, False, page, "詳細画面で募集番号を読めませんでした（--sample 募集番号 で指定してください）")
            return ""
        self.record(name, True, page, f"募集番号 {code} を見本に使います")
        return code

    def step_sample(self, page: Page, sample: str, top_url: str, export_url: str) -> None:
        """募集管理で sample（募集番号）を検索し、1件だけのときに「ファイル取出予約」して、取出ファイル一覧から CSV を落とす。"""
        name = "08_取り出し予約"
        try:
            page.goto(top_url)
            if not self.click_text(page, "募集管理"):
                self.record(name, False, page, "「募集管理」が見つかりませんでした")
                return
            if sample == "auto":
                sample = self.pick_code(page)
                if not sample:
                    return
                page.goto(top_url)
                self.click_text(page, "募集管理")
            hits = self.search_code(page, sample)
            if hits != 1:
                self.save(name, page)
                self.record(name, False, page, f"「{sample}」の検索結果が {hits if hits is not None else '?'}件 のため取り出しません"
                                               "（1件だけのときに取り出します）")
                return
            button = page.locator("a[onclick*='export_bg_csv']")
            if not button.count():
                button = page.get_by_role("link", name="ファイル取出予約", exact=True)
            if not button.count():
                self.save(name, page)
                self.record(name, False, page, "「ファイル取出予約」が見つかりませんでした")
                return
            messages = []

            def answer(d):  # 取り出しの確認ダイアログだけ「OK」で進める（この画面で開くのはこれだけ）
                messages.append(d.message)
                d.accept()
            page.on("dialog", answer)
            try:
                button.first.click()
                page.wait_for_timeout(2000)
                page.wait_for_load_state("networkidle")
            finally:
                page.remove_listener("dialog", answer)
            self.save(name, page)
            self.record(name, True, page, " / ".join(messages))
        except Exception as e:
            self.record(name, False, page, f"エラー: {e}")
            return
        if not export_url:
            self.record("09_取り出しファイル", False, page, "取出ファイル一覧の場所が分からないため、ダウンロードできません")
            return
        page.goto(export_url)
        page.wait_for_load_state("networkidle")
        self.step_download(page)

    def step_download(self, page: Page) -> None:
        """取出ファイル一覧のいちばん上の行が「完了」になるまで「最新を表示する」を押して待ち、取出しファイルを落とす。"""
        name = "09_取り出しファイル"
        started = time.time()
        try:
            for i in range(self.export_poll_times + 1):
                row = self._top_row(page)
                # 前からあった行（ほかの人や前回の取り出し）を、今回の見本と取り違えない
                new = row.count() and (self.export_top is None or self._top_key(page) != self.export_top)
                if new and "完了" in row.inner_text():
                    link = row.locator("a", has_text=".csv")
                    if not link.count():
                        link = row.locator("a[href*='csv'], a[href*='download']")
                    if link.count():
                        with page.expect_download() as d:
                            link.first.click()
                        d.value.save_as(str(self.out / "取り出し見本.csv"))
                        self.save(name, page)
                        self.record(name, True, page, f"取り出し見本.csv（{d.value.suggested_filename}）")
                        return
                if i == self.export_poll_times:
                    break
                time.sleep(self.poll_interval)
                # 「最新を表示する」の文字は画面上の注意書きにもあるので、ボタンは id で押す
                refresh = page.locator("#view_reload_button")
                if not refresh.count():
                    refresh = page.get_by_role("link", name="最新を表示する", exact=True)
                if refresh.count():
                    refresh.first.click()
                    page.wait_for_load_state("networkidle")
                else:
                    page.reload()
            self.save(name, page)
            self.record(name, False, page, f"{(time.time() - started) / 60:.0f}分待っても完了しませんでした"
                                           "（予約はヒトマネに残っています）")
        except Exception as e:
            self.save(name, page)
            self.record(name, False, page, f"エラー: {e}")


def run_survey(info: dict, out_dir: Path, headed: bool = False, sample: str = "", log=print, **opts) -> dict:
    """ログインして各画面を保存する。opts は poll_interval_ms・export_poll_times・timeout_ms。"""
    return Survey(info, out_dir, log, **opts).run(headed, sample)
