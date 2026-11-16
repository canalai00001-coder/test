"""ヒトマネ管理画面の画面調査。

管理画面は決まったネットワークからしか開けず、作る側からは画面を見られない。そこで、利用者のパソコンでログインして
各画面の HTML・スクリーンショット・リンク一覧を output に保存し、その結果を見てボタンの押し方や CSV の形を決める。

押すのは、ログイン、画面の移動、ダイアログを開く・閉じる、検索だけ。取り込み・取り下げ・掲載状態の変更はしない。
sample（募集番号）を渡したときだけ、その1件を「ファイル取出予約」して、予約一覧から CSV の見本をダウンロードする。
"""
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import Page, sync_playwright

# 予約一覧へのリンクを探すとき、押すと予約してしまうボタンは使わない
RESERVE_ACTIONS = ("取込予約", "取出予約")


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
                jobs_links = self.step_jobs(page, top_url)
                if sample:
                    self.step_sample(page, sample)
                self.step_reservations(page, top_links + jobs_links, top_url)
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
            self.record(name, True, page)
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

    def step_reservations(self, page: Page, links: list, top_url: str) -> None:
        name = "05_予約一覧"
        try:
            # 「ファイル取出予約」のような予約するボタンは除く（「…予約一覧」は除かない）
            href = next((h for t, h in links if "予約" in t and ("一覧" in t or not any(a in t for a in RESERVE_ACTIONS))
                         and h and not h.startswith("<")), None)
            if href is None:
                self.record(name, False, page, "予約一覧へのリンクが見つかりませんでした")
                return
            page.goto(urljoin(page.url, href))
            page.wait_for_load_state("networkidle")
            self.save(name, page)
            self.record(name, True, page)
        except Exception as e:
            self.record(name, False, page, f"エラー: {e}")

    def step_sample(self, page: Page, sample: str) -> None:
        """募集管理で sample（募集番号）を検索し、1件だけのときに「ファイル取出予約」して、予約一覧から CSV を落とす。"""
        name = "06_取り出し予約"
        try:
            box = page.locator("input[type=text]")
            if not box.count():
                self.save(name, page)
                self.record(name, False, page, "フリーワードの入力欄が見つかりませんでした")
                return
            box.first.fill(sample)
            search = page.get_by_role("button", name="検索", exact=True)
            if not search.count():
                search = page.get_by_text("検索", exact=True)
            search.first.click()
            page.wait_for_load_state("networkidle")
            m = re.search(r"全\s*([\d,]+)\s*件", page.inner_text("body"))
            hits = int(m.group(1).replace(",", "")) if m else None
            if hits != 1:
                self.save(name, page)
                self.record(name, False, page, f"「{sample}」の検索結果が {hits if hits is not None else '?'}件 のため取り出しません"
                                               "（1件だけのときに取り出します）")
                return
            if not self.click_text(page, "ファイル取出予約"):
                self.save(name, page)
                self.record(name, False, page, "「ファイル取出予約」が見つかりませんでした")
                return
            page.wait_for_timeout(1000)
            self.save(name, page)
            self.record(name, True, page)
        except Exception as e:
            self.record(name, False, page, f"エラー: {e}")
            return
        self.step_download(page)

    def step_download(self, page: Page) -> None:
        """予約一覧のいちばん上の行が「完了」になるまで「最新を表示する」を押して待ち、取出しファイルを落とす。"""
        name = "07_取り出しファイル"
        started = time.time()
        try:
            for i in range(self.export_poll_times + 1):
                row = page.locator("tr", has=page.locator("td")).first
                if row.count() and "完了" in row.inner_text():
                    link = row.locator("a", has_text=".csv")
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
                refresh = page.get_by_text("最新を表示する")
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
