"""ヒトマネ管理画面の共通の操作（ログイン・一覧の行・「最新を表示する」）。

画面の作りは docs/superpowers/specs/2026-11-16-hitomane-screen-survey.md（画面調査の結果）を見て決めた。
"""
import os
import re

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

# まだ終わっていない状態の文言（取込・取出ファイル一覧のステータス）
PENDING = ("待機中", "進行中", "処理中", "実行中", "取込中", "取出中", "準備中")
# 終わった行のステータス・詳細にこれがあれば失敗とみなす（行には「キャンセル」のリンクが付くことがあるので、行全体では見ない）
ERROR_WORDS = re.compile(r"エラー|失敗|不正|できません|誤り|中止")


def launch(p, headed: bool = False):
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
    kw = {"headless": not headed}
    return p.chromium.launch(executable_path=exe, **kw) if exe else p.chromium.launch(**kw)


def login(page: Page, info: dict) -> None:
    """ログインする。できなければ RuntimeError（パスワードは文言に入れない）。
    ログイン画面がたまに60秒たっても開き終わらないことがある（2026-11-17 に2回続けて。直後は0.3秒で開いた）ので、
    画面の中身が読めた時点で進め、時間切れのときは1回だけ開き直す。"""
    try:
        resp = page.goto(info["url"], wait_until="domcontentloaded")
    except PlaywrightTimeout:
        resp = page.goto(info["url"], wait_until="domcontentloaded")
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


def branches(page: Page, info: dict) -> list[dict]:
    """会社の拠点の一覧（m_branches）→ [{"code", "name"}]。列：エリア・拠点コード・…・拠点名。"""
    page.goto(url(info, "m_branches"))
    page.wait_for_load_state("networkidle")
    out = []
    rows = page.locator("tbody.records tr.record")
    for i in range(rows.count()):
        cells = [c.strip() for c in rows.nth(i).locator("td").all_inner_texts()]
        if len(cells) >= 4:
            out.append({"code": cells[1], "name": cells[3]})
    return out


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


def hide_notice(page: Page) -> None:
    """ログイン直後のトップに出る「お知らせ」の窓（colorbox）を、この画面の上だけで隠す。

    窓の「閉じる」（a.seen_notice）は押さない。押すとヒトマネ側でそのお知らせが既読になるため（2026-11-18 の画面調査）。"""
    page.evaluate("""() => { for (const id of ['colorbox', 'cboxOverlay']) {
        const e = document.getElementById(id); if (e) e.style.display = 'none'; } }""")


def open_old_import(page: Page) -> None:
    """トップ（menu）で「旧原稿形式CSV取込」のダイアログを開く。お知らせの窓は既読にしないで隠す。

    リンクは折りたたまれた欄の中で画面の外にあるので、マウスでは押せない。画面の上でクリックを起こしてサイトのダイアログを開き、
    隠したダイアログの枠を見えるように戻す（お知らせと同じ枠を使うため）。"""
    hide_notice(page)
    link = page.locator("a[href*='old_import']")
    if not link.count():
        raise RuntimeError("「旧原稿形式CSV取込」のリンクが見つかりませんでした")
    link.first.evaluate("a => a.click()")
    page.wait_for_timeout(500)
    page.evaluate("""() => { for (const id of ['colorbox', 'cboxOverlay']) {
        const e = document.getElementById(id); if (e) e.style.display = ''; } }""")


def show_section(page: Page, section: str) -> None:
    """トップの折りたたまれた欄（「＋」で開く）を、この画面の上だけで開く（「＋」は押さない。開いた状態がヒトマネ側に残るため）。"""
    page.evaluate("s => { const e = document.getElementById(s); if (e) e.style.display = 'block'; }", section)


def dialog_frame(page: Page, format_name: str = "hmgrfrm"):
    """開いているダイアログの中身の iframe のうち、取込フォームの format_name が合うもの（無ければ None）。

    hmgrfrm＝旧フォーマット、newhmgrfrm＝新フォーマット（2026-11-18 の画面調査）。旧原稿形式CSV取込は、iframe の URL が
    old_import のままとは限らない（URL で探すと見つからなかった）ので、iframe の要素から中身をたどり、フォームの種類で確かめる。"""
    for el in page.locator("iframe").element_handles():
        frame = el.content_frame()
        if frame is None:
            continue
        box = frame.locator("input[name=format_name]")
        if box.count() and box.first.get_attribute("value") == format_name and frame.locator("#file_csv").count():
            return frame
    return None
