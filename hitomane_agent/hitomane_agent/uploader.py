"""ヒトマネへの CSV の取り込み（Playwright）。

ログイン → 取込ファイル一覧のいちばん上の行を覚える → 募集管理の「ファイル取込予約」→ ダイアログ（iframe）で
ファイルを選び、「既存原稿と同じ募集番号の原稿を上書きせずに取り込む」は外したまま「ファイル取込予約」→
取込ファイル一覧で、新しくできた行が終わるまで「最新を表示する」を押して待つ。

成功とみなすのは、新しい行のステータスが「完了」で、ステータス・詳細にエラーらしい文言がないときだけ。
完了・エラーの実物の表示はまだ見ていない（2026-11-16 時点）。最初の実物の取り込みで確かめて直す。
"""
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from . import site


@dataclass
class UploadResult:
    file: str
    ok: bool
    message: str
    row_text: str = ""
    screenshot: str = ""


class HitomaneUploader:
    def __init__(self, info: dict, opts: dict, out_dir: Path, headed: bool = False, log=print):
        """opts は settings の hitomane（timeout_ms・poll_interval_ms・import_poll_times）。"""
        self.info, self.out, self.headed, self.log = info, Path(out_dir), headed, log
        self.timeout_ms = opts.get("timeout_ms", 60000)
        self.poll = opts.get("poll_interval_ms", 5000) / 1000
        self.poll_times = opts.get("import_poll_times", 360)

    def _open(self, p):
        browser = site.launch(p, self.headed)
        page = browser.new_context().new_page()
        page.set_default_timeout(self.timeout_ms)
        site.login(page, self.info)
        return browser, page

    def total(self) -> int | None:
        """募集管理の全件数（「全N件」）。"""
        with sync_playwright() as p:
            browser, page = self._open(p)
            try:
                return self._total(page)
            finally:
                browser.close()

    def _total(self, page: Page) -> int | None:
        page.goto(site.url(self.info, "rec_recruitments"))
        page.wait_for_load_state("networkidle")
        return site.count(page)

    def upload(self, files: list[Path]) -> list[UploadResult]:
        """files を順に取り込む。1つ失敗したら、残りは取り込まない。"""
        self.out.mkdir(parents=True, exist_ok=True)
        results = []
        with sync_playwright() as p:
            browser, page = self._open(p)
            try:
                for f in files:
                    r = self._one(page, Path(f))
                    results.append(r)
                    self.log(f"{'○' if r.ok else '×'} {Path(f).name}：{r.message}")
                    if not r.ok:
                        break
            finally:
                browser.close()
        return results

    def _shot(self, page: Page, name: str) -> str:
        path = self.out / f"{name}.png"
        try:
            page.screenshot(path=str(path), full_page=True)
        except Exception:
            return ""
        return str(path)

    def _one(self, page: Page, path: Path) -> UploadResult:
        label = path.stem
        try:
            page.goto(site.url(self.info, "csv_import_queues"))
            page.wait_for_load_state("networkidle")
            before = site.top_key(page)

            page.goto(site.url(self.info, "rec_recruitments"))
            page.wait_for_load_state("networkidle")
            page.locator("a[href*='select_new_format']").first.click()
            frame = self._dialog(page)
            frame.locator("#file_csv").set_input_files(str(path))
            box = frame.locator("#duplicate_check_term")
            if box.count() and box.is_checked():
                box.uncheck()  # 同じ募集番号は上書きする（チェックを付けると「_連番」付きの別の原稿になる）
            messages = []

            def answer(d):  # 「ファイル取込予約」の確認ダイアログだけ OK で進める
                messages.append(d.message)
                d.accept()
            page.on("dialog", answer)
            try:
                frame.locator("a.btn_operation_btn02").first.click()
                page.wait_for_timeout(2000)
                page.wait_for_load_state("networkidle")
            finally:
                page.remove_listener("dialog", answer)
            self._shot(page, f"{label}_取込予約")
            (self.out / f"{label}_取込予約.txt").write_text(
                "確認ダイアログ: " + " / ".join(messages) + "\n\n" + frame.locator("body").inner_text(), encoding="utf-8")
        except Exception as e:
            return UploadResult(path.name, False, f"取込予約の操作中にエラー: {e}", "", self._shot(page, f"{label}_取込予約_エラー"))
        return self._wait(page, path, before)

    def _dialog(self, page: Page):
        """取込ダイアログの中身（iframe）。"""
        deadline = time.time() + self.timeout_ms / 1000
        while time.time() < deadline:
            frame = next((f for f in page.frames if "select_new_format" in f.url), None)
            if frame is not None:
                frame.wait_for_load_state()
                frame.locator("#file_csv").wait_for(state="attached")
                return frame
            page.wait_for_timeout(300)
        raise RuntimeError("取込ダイアログが開きませんでした")

    def _wait(self, page: Page, path: Path, before: str) -> UploadResult:
        label = path.stem
        started = time.time()
        page.goto(site.url(self.info, "csv_import_queues"))
        page.wait_for_load_state("networkidle")
        text = ""
        for i in range(self.poll_times + 1):
            row = site.top_row(page)
            if row.count() and site.top_key(page) != before:
                cells = [c.strip() for c in row.locator("td").all_inner_texts()]
                text = " | ".join(cells)
                # 列：リクエスト日時・取込完了日時・データ種別・取込ファイル・ステータス・詳細・削除予定日
                status, detail = (cells[4], cells[5]) if len(cells) >= 6 else (text, text)
                if not any(w in status for w in site.PENDING):
                    shot = self._shot(page, f"{label}_取込結果")
                    (self.out / f"{label}_取込結果.txt").write_text(text, encoding="utf-8")
                    if "完了" in status and not site.ERROR_WORDS.search(status + " " + detail):
                        return UploadResult(path.name, True, f"取り込みが終わりました（{status}）", text, shot)
                    return UploadResult(path.name, False, f"取り込みが「{status}」で終わりました。詳細を確かめてください",
                                        text, shot)
            if i == self.poll_times:
                break
            if i % 6 == 5:
                self.log(f"  取込ファイル一覧で結果を待っています（{(time.time() - started) / 60:.0f}分）")
            time.sleep(self.poll)
            site.refresh(page)
        shot = self._shot(page, f"{label}_取込結果")
        return UploadResult(path.name, False, f"{(time.time() - started) / 60:.0f}分待っても取り込みが終わりませんでした"
                                              "（取込ファイル一覧で結果を確かめてください）", text, shot)
