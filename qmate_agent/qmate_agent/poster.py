"""Q-mate 管理画面への入力（Playwright）。

流れ: 新規作成ページを開く → 項目を入力 → 入力欄から値を読み戻して元データと照合
→ 全項目一致したときだけ保存ボタンを押す。1項目でも違えば保存せずに止める。
"""
import os
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from .config import ROOT
from .validate import parse_int


def _norm(v) -> str:
    s = unicodedata.normalize("NFKC", str(v if v is not None else ""))
    return " ".join(s.replace(",", "").split())


@dataclass
class PostResult:
    ok: bool
    message: str
    mismatches: list[dict] = field(default_factory=list)
    screenshot: str = ""
    url: str = ""


def launch(p, headless: bool):
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
    return p.chromium.launch(headless=headless, executable_path=exe) if exe else p.chromium.launch(headless=headless)


class QmatePoster:
    def __init__(self, form_cfg: dict, auth_file: Path = ROOT / ".auth" / "qmate.json",
                 headless: bool = True, shots_dir: Path = ROOT / "output" / "screens"):
        self.cfg = form_cfg
        self.auth_file = auth_file
        self.headless = headless
        self.shots_dir = shots_dir

    # ---- ログイン -------------------------------------------------------
    def save_login_manually(self) -> None:
        """ブラウザを開いて人がログインし、そのセッションを保存する（2段階認証にも対応できる）。"""
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = launch(p, headless=False)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(self.cfg["login"]["url"])
            input("ブラウザでログインが終わったら Enter を押してください > ")
            ctx.storage_state(path=str(self.auth_file))
            browser.close()
        print(f"ログイン状態を保存しました: {self.auth_file}")

    def _login_if_needed(self, page: Page) -> None:
        login = self.cfg["login"]
        page.goto(self.cfg.get("base_url") or login["url"])
        if login.get("logged_in_selector") and page.locator(login["logged_in_selector"]).count():
            return
        user, pw = os.environ.get("QMATE_ID"), os.environ.get("QMATE_PASSWORD")
        if not (user and pw):
            raise RuntimeError("ログインしていません。`python -m qmate_agent login` を先に実行するか、"
                               "QMATE_ID / QMATE_PASSWORD を設定してください")
        page.goto(login["url"])
        page.fill(login["id_selector"], user)
        page.fill(login["password_selector"], pw)
        page.click(login["submit_selector"])
        page.wait_for_load_state("networkidle")
        if login.get("logged_in_selector"):
            page.wait_for_selector(login["logged_in_selector"], timeout=15000)

    # ---- 入力と照合 -----------------------------------------------------
    @staticmethod
    def _form_value(spec: dict, raw: str):
        vmap = spec.get("value_map")
        if vmap is not None:
            return vmap.get(raw, raw)
        if spec.get("format") == "int" and raw:
            n = parse_int(raw)  # "1,600円" → "1600"
            return str(n) if n is not None else raw
        return raw

    def fill(self, page: Page, job: dict) -> None:
        for spec in self.cfg["fields"]:
            value = self._form_value(spec, job.get(spec["key"], ""))
            loc = page.locator(spec["selector"])
            action = spec.get("action", "fill")
            if action == "fill":
                loc.fill(str(value))
            elif action == "select":
                if value == "":
                    continue
                loc.select_option(label=str(value))
            elif action == "check":
                loc.set_checked(bool(value))
            elif action == "radio":
                page.locator(f"{spec['selector']}[value='{value}']").check()
            else:
                raise ValueError(f"未対応の action: {action}")
        page.wait_for_timeout(self.cfg.get("wait_ms_after_fill", 300))

    def read_back(self, page: Page) -> dict:
        out = {}
        for spec in self.cfg["fields"]:
            loc = page.locator(spec["selector"])
            action = spec.get("action", "fill")
            if action == "fill":
                out[spec["key"]] = loc.input_value()
            elif action == "select":
                out[spec["key"]] = loc.evaluate("e => e.selectedIndex >= 0 && e.value !== '' ? e.options[e.selectedIndex].text : ''")
            elif action == "check":
                out[spec["key"]] = loc.is_checked()
            elif action == "radio":
                checked = page.locator(f"{spec['selector']}:checked")
                out[spec["key"]] = checked.get_attribute("value") if checked.count() else ""
        return out

    def compare(self, job: dict, actual: dict) -> list[dict]:
        mismatches = []
        for spec in self.cfg["fields"]:
            key = spec["key"]
            expected = self._form_value(spec, job.get(key, ""))
            got = actual.get(key)
            if isinstance(expected, bool) or isinstance(got, bool):
                same = bool(expected) == bool(got)
            else:
                same = _norm(expected) == _norm(got)
            if not same:
                mismatches.append({"field": key, "expected": expected, "actual": got})
        return mismatches

    # ---- 1件投稿 --------------------------------------------------------
    def post_one(self, page: Page, job: dict, dry_run: bool = False) -> PostResult:
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        shot = self.shots_dir / f"{job.get('job_no', 'unknown')}.png"
        page.goto(self.cfg["new_job_url"])
        self.fill(page, job)
        mismatches = self.compare(job, self.read_back(page))
        page.screenshot(path=str(shot), full_page=True)
        if mismatches:
            return PostResult(False, "入力後の値が元データと一致しないため保存していません", mismatches, str(shot))
        mode = self.cfg.get("submit_mode", "draft")
        if dry_run or mode == "none":
            return PostResult(True, "入力・照合まで完了（保存はしていません）", [], str(shot), page.url)
        button = self.cfg["publish_button"] if mode == "publish" else self.cfg["draft_button"]
        page.click(button)
        if self.cfg.get("success_selector"):
            page.wait_for_selector(self.cfg["success_selector"], timeout=20000)
        page.screenshot(path=str(shot.with_name(shot.stem + "_saved.png")), full_page=True)
        label = "公開" if mode == "publish" else "下書き保存"
        return PostResult(True, f"{label}しました", [], str(shot), page.url)

    def run(self, jobs: list[dict], dry_run: bool = False, on_result=None) -> list[PostResult]:
        results = []
        with sync_playwright() as p:
            browser = launch(p, headless=self.headless)
            state = str(self.auth_file) if self.auth_file.exists() else None
            ctx = browser.new_context(storage_state=state)
            page = ctx.new_page()
            page.set_default_timeout(self.cfg.get("timeout_ms", 10000))
            if not self.cfg.get("skip_login"):
                self._login_if_needed(page)
            for job in jobs:
                try:
                    r = self.post_one(page, job, dry_run=dry_run)
                except Exception as e:  # 1件の失敗で全体を止めない
                    r = PostResult(False, f"操作中にエラー: {e}")
                results.append(r)
                if on_result:
                    on_result(job, r)
            browser.close()
        return results
