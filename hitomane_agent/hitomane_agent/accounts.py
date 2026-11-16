"""ヒトマネのログイン情報。

通勤用スプレッドシートの「ヒトマネログイン情報」シートから読む（無ければ「Q-mateログイン情報」シートの「ヒトマネ」の行）。
ヒトマネは1つのログインで全社の原稿を扱うので、行は1つでよい。「ヒトマネログイン情報」シートに会社名の列がなければ、
ログインIDの入っている最初の行を使う。
そのスプレッドシートが「リンクを知っている全員」などに共有されているあいだは、パスワードが誰にでも見えるため使わない。
"""
from . import config


def parse_rows(values: list) -> list[dict]:
    """シートの表 → [{"company", "login_id", "password", "url", "memo"}]（ログインIDのない行は飛ばす）。"""
    if not values:
        return []
    head = [str(h).strip() for h in values[0]]
    col = lambda *words: next((i for i, h in enumerate(head) if any(w in h for w in words)), None)
    ci, ii, pi, ui, mi = col("会社"), col("ID", "ＩＤ"), col("パスワード"), col("URL"), col("メモ", "担当")
    if None in (ii, pi):
        raise RuntimeError("ログイン情報シートの見出しに「ログインID」と「パスワード」を入れてください")
    cell = lambda r, i: str(r[i]).strip() if i is not None and i < len(r) else ""
    return [{"company": cell(r, ci), "login_id": cell(r, ii), "password": cell(r, pi), "url": cell(r, ui),
             "memo": cell(r, mi)} for r in values[1:] if cell(r, ii)]


def _open(settings: dict):
    import gspread

    gc = gspread.service_account(filename=str(config.ROOT / settings["service_account_file"]))
    return gc.open_by_key(settings["login_spreadsheet_id"])


def login_info(settings: dict, book=None) -> dict:
    """{"login_id", "password", "url"}（url が空ならヒトマネ管理画面の URL）。

    ヒトマネは担当者ごとにログインIDがある。settings の login_user（ログインIDかメモの名前。settings.local.json に書く）
    があればその行、なければ会社名「ヒトマネ」の行、それも無ければ専用シートの最初の行を使う。
    """
    import gspread

    book = book or _open(settings)
    name, user = settings["login_company"], (settings.get("login_user") or "").strip()
    sheets = settings["accounts_sheets"]
    r, sheet = None, sheets[0]
    for sheet in sheets:
        try:
            rows = parse_rows(book.worksheet(sheet).get_all_values())
        except gspread.WorksheetNotFound:
            continue
        own = name in sheet  # 「ヒトマネログイン情報」のようなヒトマネ専用のシート
        if user and own:
            r = next((x for x in rows if x["login_id"] == user or (x["memo"] and user in x["memo"])), None)
            if r is None:
                raise RuntimeError(f"「{sheet}」シートに、ログインIDかメモが「{user}」の行がありません"
                                   "（settings.local.json の login_user を確かめてください）")
        else:
            r = next((x for x in rows if x["company"] == name), None) or (
                next((x for x in rows if not x["company"]), rows[0] if rows else None) if own else None)
        if r:
            break
    if r is None:
        raise RuntimeError(f"「{sheets[0]}」シートにヒトマネのログインIDとパスワードを入れてください"
                           f"（または「{sheets[-1]}」シートに『{name}』の行を足してください）")
    if any(p.get("type") in ("anyone", "domain") for p in book.list_permissions()):
        raise RuntimeError("ログイン情報のあるスプレッドシートが「リンクを知っている全員」に共有されているため、"
                           "パスワードは使いません。共有を「制限付き」にしてから実行してください")
    if not r["password"]:
        raise RuntimeError(f"{sheet}シートの {r['login_id']} のパスワードが空欄です")
    return {"login_id": r["login_id"], "password": r["password"], "url": r["url"] or settings["hitomane"]["base_url"]}
