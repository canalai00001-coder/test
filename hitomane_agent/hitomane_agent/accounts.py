"""ヒトマネのログイン情報。

Q-mate と同じく、通勤用スプレッドシートの「Q-mateログイン情報」シートに、会社名「ヒトマネ」の行を足して管理する
（ヒトマネは1つのログインで全社の原稿を扱うので、行は1つ）。
そのスプレッドシートが「リンクを知っている全員」などに共有されているあいだは、パスワードが誰にでも見えるため使わない。
"""
from . import config


def parse_sheet(values: list) -> dict:
    """シートの表 → {会社名: {"login_id", "password", "url"}}。会社名とログインID のない行は飛ばす。"""
    if not values:
        return {}
    head = [str(h).strip() for h in values[0]]
    col = lambda *words: next((i for i, h in enumerate(head) if any(w in h for w in words)), None)
    ci, ii, pi, ui = col("会社"), col("ID", "ＩＤ"), col("パスワード"), col("URL")
    if None in (ci, ii, pi):
        raise RuntimeError("ログイン情報シートの見出しは「会社名・ログインID・パスワード・…URL」にしてください")
    cell = lambda r, i: str(r[i]).strip() if i is not None and i < len(r) else ""
    rows = {}
    for r in values[1:]:
        company, login_id = cell(r, ci), cell(r, ii)
        if company and login_id:
            rows[company] = {"login_id": login_id, "password": cell(r, pi), "url": cell(r, ui)}
    return rows


def _open(settings: dict):
    import gspread

    gc = gspread.service_account(filename=str(config.ROOT / settings["service_account_file"]))
    return gc.open_by_key(settings["login_spreadsheet_id"])


def login_info(settings: dict, book=None) -> dict:
    """{"login_id", "password", "url"}（url が空ならヒトマネ管理画面の URL）。"""
    book = book or _open(settings)
    name, sheet = settings["login_company"], settings["accounts_sheet"]
    rows = parse_sheet(book.worksheet(sheet).get_all_values())
    if name not in rows:
        raise RuntimeError(f"{sheet}シートに『{name}』の行を足してください（会社名に「{name}」、ログインID とパスワード）")
    if any(p.get("type") in ("anyone", "domain") for p in book.list_permissions()):
        raise RuntimeError(f"ログイン情報のあるスプレッドシートが「リンクを知っている全員」に共有されているため、"
                           "パスワードは使いません。共有を「制限付き」にしてから実行してください")
    r = rows[name]
    if not r["password"]:
        raise RuntimeError(f"{sheet}シートの『{name}』のパスワードが空欄です")
    return {"login_id": r["login_id"], "password": r["password"], "url": r["url"] or settings["hitomane"]["base_url"]}
