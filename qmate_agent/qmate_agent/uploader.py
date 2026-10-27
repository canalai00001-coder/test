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
        user, pw = os.environ.get("QMATE_ID"), os.environ.get("QMATE_PASSWORD")
        if not (user and pw):
            raise RuntimeError("環境変数 QMATE_ID / QMATE_PASSWORD を設定してください")
        page.goto(self.cfg["login_url"])
        _first(page, self.cfg["id_selectors"]).fill(user)
        _first(page, self.cfg["password_selectors"]).fill(pw)
        _first(page, self.cfg["login_button_selectors"]).click()
        page.wait_for_load_state("networkidle")
        if "user_sessions" in page.url:
            raise RuntimeError("ログインできませんでした。ID・パスワードを確認してください")

    def _result_text(self, page: Page) -> str:
        loc = page.locator(self.cfg.get("result_selector", "body"))
        return loc.first.inner_text() if loc.count() else ""

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
