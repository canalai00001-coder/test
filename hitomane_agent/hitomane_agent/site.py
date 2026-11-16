"""ヒトマネ管理画面の共通の操作（ログイン・一覧の行・「最新を表示する」）。

画面の作りは docs/superpowers/specs/2026-11-16-hitomane-screen-survey.md（画面調査の結果）を見て決めた。
"""
import os
import re

from playwright.sync_api import Page

# まだ終わっていない状態の文言（取込・取出ファイル一覧のステータス）
PENDING = ("待機中", "処理中", "実行中", "取込中", "取出中", "準備中")
# 終わった行のステータス・詳細にこれがあれば失敗とみなす（行には「キャンセル」のリンクが付くことがあるので、行全体では見ない）
ERROR_WORDS = re.compile(r"エラー|失敗|不正|できません|誤り|中止")


def launch(p, headed: bool = False):
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
    kw = {"headless": not headed}
    return p.chromium.launch(executable_path=exe, **kw) if exe else p.chromium.launch(**kw)


def login(page: Page, info: dict) -> None:
    """ログインする。できなければ RuntimeError（パスワードは文言に入れない）。"""
    resp = page.goto(info["url"])
    if resp is not None and resp.status == 403:
        raise RuntimeError("管理画面を開けませんでした（403）。社内のネットワークから実行してください")
    pw = page.locator("input[type=password]")
    user = page.locator("input[type=text], input[type=email], input:not([type])")
    if not pw.count() or not user.count():
        raise RuntimeError("ログイン画面の入力欄が見つかりませんでした")
    user.first.fill(info["login_id"])
    pw.first.fill(info["password"])
    button = page.locator("button[type=submit], input[type=submit]")
    if not button.count():
        button = page.get_by_role("button", name="ログイン")
    button.first.click()
    page.wait_for_load_state("networkidle")
    if page.locator("input[type=password]").count():
        raise RuntimeError(f"ログインできませんでした（{info['login_id']}。ID・パスワードを確かめてください）")


def url(info: dict, path: str) -> str:
    """管理画面の URL（info["url"] は https://kanri.hitomgr.jp/m66w/ の形）。"""
    return info["url"].rstrip("/") + "/" + path.lstrip("/")


def top_row(page: Page):
    """一覧のいちばん上の行。行は tbody.records の tr.record（tbody.messages の「見つかりませんでした」は見ない）。"""
    rows = page.locator("tbody.records tr.record")
    if rows.count():
        return rows.first
    return page.locator("tbody.records tr", has=page.locator("td")).first


def top_key(page: Page) -> str:
    """いちばん上の行のリクエスト日時（最初の列）。行がなければ空。"""
    row = top_row(page)
    return row.locator("td").first.inner_text().strip() if row.count() else ""


def refresh(page: Page) -> None:
    """「最新を表示する」を押す（同じ文字が注意書きにもあるので id で押す）。無ければ読み込み直す。"""
    button = page.locator("#view_reload_button")
    if button.count():
        button.first.click()
        page.wait_for_load_state("networkidle")
    else:
        page.reload()


def count(page: Page) -> int | None:
    """画面の「全N件」。"""
    m = re.search(r"全\s*([\d,]+)\s*件", page.inner_text("body"))
    return int(m.group(1).replace(",", "")) if m else None
