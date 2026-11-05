"""Q-mate への CSV 入稿（Playwright）。

ログイン → CSV 一括入稿ページ → ファイルを選んで取り込み → 結果欄の文言を読んで成否を判定。
Q-mate の取り込みは受付後に裏で処理されるので、「最後に受付したCSV取込」の欄が
取り込み前と変わり、成功かエラーの表示になるまでページを読み込み直して待つ。
結果欄の文言とスクリーンショットは output/ に残す。
"""
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from .config import ROOT


@dataclass
class UploadResult:
    ok: bool
    message: str
    page_text: str = ""
    screenshot: str = ""


def launch(p, headless: bool):
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
    return p.chromium.launch(headless=headless, executable_path=exe) if exe else p.chromium.launch(headless=headless)


def _first(page: Page, selectors: list[str]):
    for s in selectors:
        loc = page.locator(s)
        if loc.count():
            return loc.first
    raise RuntimeError(f"画面に見つかりません: {selectors}")


class QmateUploader:
    def __init__(self, cfg: dict, headless: bool = True, out_dir: Path = ROOT / "output"):
        self.cfg = cfg
        self.headless = headless
        self.out_dir = out_dir

    def _login(self, page: Page) -> None:
        # 会社ごとに登録したログイン情報（accounts.qmate_config が入れる）。無ければ環境変数
        user = self.cfg.get("login_id") or os.environ.get("QMATE_ID")
        pw = self.cfg.get("password") or os.environ.get("QMATE_PASSWORD")
        if not (user and pw):
            raise RuntimeError("Q-mate のログイン情報がありません。操作画面の「会社」タブで登録してください")
        page.goto(self.cfg["login_url"])
        _first(page, self.cfg["id_selectors"]).fill(user)
        _first(page, self.cfg["password_selectors"]).fill(pw)
        _first(page, self.cfg["login_button_selectors"]).click()
        page.wait_for_load_state("networkidle")
        if "user_sessions" in page.url:
            raise RuntimeError("ログインできませんでした。ID・パスワードを確認してください")
        self.after_login_url = page.url
        # CSV取込画面の co が分からないとき（ログイン情報シートの URL 欄が空欄）は、ログイン後の画面のリンクから探す
        if "co=" not in self.cfg["upload_url"]:
            co = self._find_co(page)
            if co:
                self.cfg = dict(self.cfg, upload_url=f"{self.cfg['upload_url']}?co={co}")

    @staticmethod
    def _links(page: Page) -> list:
        """画面のリンク（文字とアドレス）。CSV取込画面への行き方を調べるため。"""
        try:
            pairs = page.eval_on_selector_all(
                "a[href]", "els => els.map(e => [(e.innerText || '').trim().slice(0, 30), e.getAttribute('href')])")
        except Exception:
            return []
        seen, out = set(), []
        for t, h in pairs:
            if h and not h.startswith(("#", "javascript", "mailto")) and h not in seen:
                seen.add(h)
                out.append((t.replace("\n", " "), h))
        return out

    @staticmethod
    def _find_co(page: Page) -> str:
        """ログイン直後の画面から、この会社の co（Q-mate の会社番号）を探す。

        1. co= の付いたリンク  2. 企業情報管理などの /companies/番号 のリンク（co と同じ番号）
        3. 求人情報一覧の画面にある CSV取込画面（bulk_new?co=）へのリンク
        """
        def hrefs():
            return page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href') || '')")

        def pick(pattern, urls):
            cos = {m.group(1) for u in urls for m in [re.search(pattern, u)] if m}
            if len(cos) > 1:
                raise RuntimeError(f"このアカウントでは複数の会社（{', '.join(sorted(cos))}）を扱えます。"
                                   "ログイン情報シートの URL 欄に、入稿する会社の CSV取込画面の URL を入れてください")
            return cos.pop() if cos else ""

        co = pick(r"[?&]co=(\d+)", [page.url] + hrefs()) or pick(r"/companies/(\d+)", hrefs())
        if co:
            return co
        page.goto(re.sub(r"(https?://[^/]+).*", r"\1/job_offers", page.url))
        return pick(r"[?&]co=(\d+)", [h for h in hrefs() if "bulk" in h or "co=" in h])

    def _result_text(self, page: Page) -> str:
        loc = page.locator(self.cfg.get("result_selector", "body"))
        return loc.first.inner_text() if loc.count() else ""

    def _wait_ready(self, page: Page) -> None:
        """前の取り込みを処理している間は、Q-mate がアップロードボタンを押せなくするので、押せるまで読み込み直す。"""
        times = self.cfg.get("result_poll_times", 0)
        for i in range(times + 1):
            if page.locator(self.cfg["upload_button_selector"]).first.is_enabled():
                return
            if i < times:
                time.sleep(self.cfg.get("result_poll_interval_ms", 5000) / 1000)
                page.goto(self.cfg["upload_url"])
        raise RuntimeError("前の CSV 取込がまだ処理中で、アップロードボタンが押せません。しばらくしてからやり直してください")

    def _wait_result(self, page: Page, before: str) -> str:
        """結果欄が取り込み前と変わり、成功かエラーの文言が出るまで読み込み直す。"""
        times = self.cfg.get("result_poll_times", 0)
        for i in range(times + 1):
            text = self._result_text(page)
            if text != before and (re.search(self.cfg["error_pattern"], text)
                                   or re.search(self.cfg["success_pattern"], text)):
                return text
            if i < times:
                time.sleep(self.cfg.get("result_poll_interval_ms", 5000) / 1000)
                page.goto(self.cfg["upload_url"])
        return text

    def export_template(self, status: str, out_path: Path, memo: str = "") -> Path:
        """CSV取込画面のテンプレート出力で、今 Q-mate にある原稿を CSV で取り出す。

        「出力予約」を押すと裏で出力が作られるので、「最後に受付したテンプレート出力」の欄が
        押す前と変わって成功になるまで読み込み直し、ダウンロードして out_path に保存する。
        """
        log_sel = self.cfg["export_log_selector"]
        with sync_playwright() as p:
            browser = launch(p, self.headless)
            page = browser.new_context(accept_downloads=True).new_page()
            page.set_default_timeout(self.cfg.get("timeout_ms", 60000))
            try:
                self._login(page)
                page.goto(self.cfg["upload_url"])
                before = page.locator(log_sel).first.inner_text()
                page.select_option(self.cfg["export_status_selector"], label=status)
                page.fill(self.cfg["export_memo_selector"], memo)
                page.click(self.cfg["export_button_selector"])
                page.wait_for_load_state("networkidle")
                times = self.cfg.get("export_poll_times", 120)
                for i in range(times + 1):
                    text = page.locator(log_sel).first.inner_text()
                    if text != before and re.search(self.cfg["error_pattern"], text):
                        raise RuntimeError(f"テンプレート出力が失敗しました: {text}")
                    if text != before and re.search(self.cfg["success_pattern"], text):
                        break
                    if i == times:
                        raise RuntimeError("時間内にテンプレート出力が終わりませんでした")
                    time.sleep(self.cfg.get("result_poll_interval_ms", 5000) / 1000)
                    page.goto(self.cfg["upload_url"])
                with page.expect_download() as d:
                    page.locator(log_sel).first.locator("a", has_text="ダウンロード").first.click()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                d.value.save_as(str(out_path))
            finally:
                browser.close()
        return out_path

    def check_login(self) -> str:
        """ログインして CSV取込画面を開けるか確かめる。開けた画面のタイトル（会社名など）を返す。"""
        with sync_playwright() as p:
            browser = launch(p, self.headless)
            page = browser.new_page()
            page.set_default_timeout(self.cfg.get("timeout_ms", 60000))
            try:
                self._login(page)
                links = self._links(page)
                page.goto(self.cfg["upload_url"])
                if "user_sessions" in page.url or not page.locator(self.cfg["upload_button_selector"]).count():
                    self.out_dir.mkdir(parents=True, exist_ok=True)
                    shot = self.out_dir / "ログイン確認_開けなかった画面.png"
                    page.screenshot(path=str(shot), full_page=True)
                    raise RuntimeError(
                        "ログインはできましたが、CSV取込画面を開けませんでした。会社番号（co=）を確認してください\n"
                        f"  ログイン直後の画面: {getattr(self, 'after_login_url', '')}\n"
                        f"  CSV取込画面を開こうとして移った画面: {page.title()}（{page.url}）\n"
                        f"  ログイン直後の画面にあったリンク（{len(links)}件）:\n"
                        + "\n".join(f"    {t} → {h}" for t, h in links[:40])
                        + f"\n  画面の写真: {shot}")
                self.opened_url = page.url
                return f"{page.title()}（{page.url}）"
            finally:
                browser.close()

    def upload(self, csv_path: Path, label: str) -> UploadResult:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        shot = self.out_dir / f"{label}_入稿結果.png"
        with sync_playwright() as p:
            browser = launch(p, self.headless)
            page = browser.new_page()
            page.set_default_timeout(self.cfg.get("timeout_ms", 60000))
            try:
                self._login(page)
                page.goto(self.cfg["upload_url"])
                self._wait_ready(page)
                before = self._result_text(page)
                page.set_input_files(self.cfg["file_input_selector"], str(csv_path))
                page.click(self.cfg["upload_button_selector"])
                page.wait_for_load_state("networkidle")
                text = self._wait_result(page, before)
                page.screenshot(path=str(shot), full_page=True)
            except Exception as e:
                try:
                    page.screenshot(path=str(shot), full_page=True)
                except Exception:
                    pass
                return UploadResult(False, f"操作中にエラー: {e}", "", str(shot))
            finally:
                browser.close()

        (self.out_dir / f"{label}_入稿結果.txt").write_text(text, encoding="utf-8")
        if re.search(self.cfg["error_pattern"], text):
            return UploadResult(False, "結果画面にエラーの文言があります。画面の内容を確認してください", text, str(shot))
        if not re.search(self.cfg["success_pattern"], text):
            return UploadResult(False, "時間内に取り込みが終わりませんでした。Q-mate の CSV取込画面で結果を確認してください", text, str(shot))
        return UploadResult(True, "取り込みが完了しました", text, str(shot))
