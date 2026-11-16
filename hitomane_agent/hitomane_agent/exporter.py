"""取り下げのための取り出し（Playwright）。

拠点の一覧（m_branches）でアカウントの拠点を読む → 取出ファイル一覧のいちばん上の行を覚える →
募集管理で掲載開始日の期間・掲載のみで検索して件数を読む → 「ファイル取出予約」→ 取出ファイル一覧で
新しい行が完了になるまで待ち、取出しファイル（CSV）を落とす。取り込みはしない。
"""
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from . import site
from .takedown import Conditions

# 日付の欄は、画面の入力欄と、検索で送られる隠れた欄（年・月・日）の両方に入れる
SET_DAY = """([field, y, m, d]) => {
  document.getElementById(field).value = `${y}/${String(m).padStart(2, '0')}/${String(d).padStart(2, '0')}`;
  document.getElementById(field + '_year').value = String(y);
  document.getElementById(field + '_month').value = String(m);
  document.getElementById(field + '_day').value = String(d);
}"""


class HitomaneExporter:
    def __init__(self, info: dict, opts: dict, out_dir: Path, headed: bool = False, log=print):
        self.info, self.out, self.headed, self.log = info, Path(out_dir), headed, log
        self.timeout_ms = opts.get("timeout_ms", 60000)
        self.poll = opts.get("poll_interval_ms", 5000) / 1000
        self.poll_times = opts.get("export_poll_times", 360)

    def _run(self, fn):
        with sync_playwright() as p:
            browser = site.launch(p, self.headed)
            page = browser.new_context(accept_downloads=True).new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                site.login(page, self.info)
                return fn(page)
            finally:
                browser.close()

    def branch(self) -> dict:
        return self._run(self._branch)

    def _branch(self, page: Page) -> dict:
        """アカウントの拠点（拠点の一覧の行が1つだけのとき）。列：エリア・拠点コード・…・拠点名。"""
        page.goto(site.url(self.info, "m_branches"))
        page.wait_for_load_state("networkidle")
        rows = page.locator("tbody.records tr.record")
        if rows.count() != 1:
            raise RuntimeError(f"このアカウントの拠点が {rows.count()}つあります。どの拠点の原稿かを決められないため止めます")
        cells = [c.strip() for c in rows.first.locator("td").all_inner_texts()]
        return {"code": cells[1], "name": cells[3]}

    def export(self, cond: Conditions, out_path: Path) -> dict:
        """{"count": 検索の件数, "branch": 拠点, "file": 落とした CSV（0件なら None）}"""
        return self._run(lambda page: self._export(page, cond, Path(out_path)))

    def _search(self, page: Page, cond: Conditions) -> int | None:
        page.goto(site.url(self.info, "rec_recruitments"))
        page.wait_for_load_state("networkidle")
        before = site.count(page)
        page.locator("#search_freeword").fill("")
        page.evaluate(SET_DAY, ["posted_start_from", cond.start_from.year, cond.start_from.month, cond.start_from.day])
        page.evaluate(SET_DAY, ["posted_start_to", cond.start_to.year, cond.start_to.month, cond.start_to.day])
        box = page.locator("#search_condition_posted_only")
        if box.is_checked() != cond.posted_only:
            box.set_checked(cond.posted_only)
        page.locator("a.btn_search_btn02").first.click()
        started = time.time()
        while time.time() - started < self.timeout_ms / 1000:
            page.wait_for_timeout(500)
            if page.locator("#search_freeword").is_enabled() and (site.count(page) != before or time.time() - started > 5):
                break
        page.wait_for_load_state("networkidle")
        return site.count(page)

    def _export(self, page: Page, cond: Conditions, out_path: Path) -> dict:
        branch = self._branch(page)
        page.goto(site.url(self.info, "csv_export_queues"))
        page.wait_for_load_state("networkidle")
        before = site.top_key(page)
        count = self._search(page, cond)
        self.log(f"{cond.describe()} の原稿：{count}件")
        if not count:
            return {"count": count or 0, "branch": branch, "file": None}
        messages = []

        def answer(d):  # 「ファイル取出予約」の確認ダイアログだけ OK で進める
            messages.append(d.message)
            d.accept()
        page.on("dialog", answer)
        try:
            page.locator("a[onclick*='export_bg_csv']").first.click()
            page.wait_for_timeout(2000)
        finally:
            page.remove_listener("dialog", answer)
        page.goto(site.url(self.info, "csv_export_queues"))
        page.wait_for_load_state("networkidle")
        started = time.time()
        for i in range(self.poll_times + 1):
            row = site.top_row(page)
            if row.count() and site.top_key(page) != before:
                cells = [c.strip() for c in row.locator("td").all_inner_texts()]
                status = cells[2] if len(cells) > 2 else " ".join(cells)
                if not any(w in status for w in site.PENDING):
                    if "完了" not in status:
                        raise RuntimeError(f"取り出しが「{status}」で終わりました：{' | '.join(cells)}")
                    link = row.locator("a[href*='download'], a[href*='.csv'], a", has_text=".csv")
                    if not link.count():
                        link = row.locator("a[href*='download']")
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    with page.expect_download() as d:
                        link.first.click()
                    d.value.save_as(str(out_path))
                    self.log(f"取り出しました：{' | '.join(cells)}")
                    return {"count": count, "branch": branch, "file": str(out_path), "row": " | ".join(cells)}
            if i == self.poll_times:
                break
            if i % 6 == 5:
                self.log(f"  取出ファイル一覧で完了を待っています（{(time.time() - started) / 60:.0f}分）")
            time.sleep(self.poll)
            site.refresh(page)
        raise RuntimeError(f"{(time.time() - started) / 60:.0f}分待っても取り出しが完了しませんでした"
                           "（予約はヒトマネに残っています。取出ファイル一覧を確かめてください）")
