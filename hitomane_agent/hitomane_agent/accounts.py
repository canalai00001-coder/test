"""ヒトマネのログイン情報と会社の一覧。

ヒトマネは会社ごとに管理画面の URL が違う（https://kanri.hitomgr.jp/<会社のコード>/login。例：canal benefits株式会社は m66w、
GritMate株式会社は o3h3）。ログインID・パスワードは担当者ごとで、どの会社でも同じ。

通勤用スプレッドシートの「ヒトマネログイン情報」シートから読む（無ければ「Q-mateログイン情報」シートの「ヒトマネ」の行）。
  - 会社名が空欄の行：担当者のログインID・パスワード（メモに担当者の名前）
  - 会社名の入った行：その会社の管理画面の URL（見出しのない列に入っていてもよい。kanri.hitomgr.jp の URL を探す）
そのスプレッドシートが「リンクを知っている全員」などに共有されているあいだは、パスワードが誰にでも見えるため使わない。
"""
import re

from . import config

HITOMANE_URL = re.compile(r"https?://kanri\.hitomgr\.jp/([A-Za-z0-9_-]+)")


def base_url(url: str) -> tuple[str, str] | None:
    """https://kanri.hitomgr.jp/o3h3/login → ("o3h3", "https://kanri.hitomgr.jp/o3h3/")。ヒトマネの URL でなければ None。"""
    m = HITOMANE_URL.search(url or "")
    return (m.group(1), f"https://kanri.hitomgr.jp/{m.group(1)}/") if m else None


def parse_rows(values: list) -> list[dict]:
    """シートの表 → [{"company", "login_id", "password", "url", "memo"}]（ログインIDのない行は飛ばす）。
    url は URL の列、そこにヒトマネの URL がなければ行のどこかにあるヒトマネの URL。"""
    if not values:
        return []
    head = [str(h).strip() for h in values[0]]
    col = lambda *words: next((i for i, h in enumerate(head) if any(w in h for w in words)), None)
    ci, ii, pi, ui, mi = col("会社"), col("ID", "ＩＤ"), col("パスワード"), col("URL"), col("メモ", "担当")
    if None in (ii, pi):
        raise RuntimeError("ログイン情報シートの見出しに「ログインID」と「パスワード」を入れてください")
    cell = lambda r, i: str(r[i]).strip() if i is not None and i < len(r) else ""

    def url(r):
        u = cell(r, ui)
        if base_url(u):
            return u
        return next((str(c).strip() for i, c in enumerate(r) if i != pi and base_url(str(c))), u)

    return [{"company": cell(r, ci), "login_id": cell(r, ii), "password": cell(r, pi), "url": url(r),
             "memo": cell(r, mi)} for r in values[1:] if cell(r, ii)]


def companies_from(rows: list[dict], settings: dict) -> list[dict]:
    """会社名とヒトマネの URL の入った行 → [{"company", "code", "url"}]（同じコードは1つにまとめる）。"""
    out, seen = [], set()
    for r in rows:
        b = base_url(r["url"])
        if r["company"] and r["company"] != settings["login_company"] and b and b[0] not in seen:
            seen.add(b[0])
            out.append({"company": r["company"], "code": b[0], "url": b[1]})
    return out


def find_company(companies: list[dict], name: str) -> dict:
    """会社名・会社のコード・会社名の一部（どれか1社に決まるとき）で探す。"""
    key = name.strip().lower()
    hit = [c for c in companies if key in (c["company"].lower(), c["code"].lower())]
    hit = hit or [c for c in companies if key in c["company"].lower()]
    if len(hit) != 1:
        names = "、".join(f"{c['company']}（{c['code']}）" for c in companies) or "なし"
        why = "見つかりません" if not hit else "1社に決まりません"
        raise RuntimeError(f"会社「{name}」が{why}。ログイン情報シートにある会社：{names}")
    return hit[0]


def _open(settings: dict):
    import gspread

    gc = gspread.service_account(filename=str(config.ROOT / settings["service_account_file"]))
    return gc.open_by_key(settings["login_spreadsheet_id"])


def _read(settings: dict, book):
    """(シート名, 行) を上のシートから順に（無いシートは飛ばす。見つかったところで止められるよう1つずつ読む）。"""
    import gspread

    for sheet in settings["accounts_sheets"]:
        try:
            values = book.worksheet(sheet).get_all_values()
        except gspread.WorksheetNotFound:
            continue
        yield sheet, parse_rows(values)


def companies(settings: dict, book=None) -> list[dict]:
    """ヒトマネの会社の一覧（パスワードは含まない）。"""
    book = book or _open(settings)
    own = next((rows for sheet, rows in _read(settings, book) if settings["login_company"] in sheet), None)
    return companies_from(own, settings) if own else []


def login_info(settings: dict, book=None, company: str | None = None) -> dict:
    """{"login_id", "password", "url", "company", "code"}。

    ID・パスワード：settings の login_user（ログインIDかメモの名前。settings.local.json に書く）の行（会社名が空欄の行を優先）、
    なければ会社名「ヒトマネ」の行、それも無ければ専用シートの会社名が空欄の最初の行。
    URL：company（引数、なければ settings の company）の会社の URL。会社を指定しないときは、会社が1社だけならその会社、
    会社の行が無ければ担当者の行の URL か settings の base_url。
    """
    book = book or _open(settings)
    name, user = settings["login_company"], (settings.get("login_user") or "").strip()
    company = (company or settings.get("company") or "").strip()
    sheets = settings["accounts_sheets"]
    r, sheet, comps = None, sheets[0], []
    for sheet, rows in _read(settings, book):
        own = name in sheet  # 「ヒトマネログイン情報」のようなヒトマネ専用のシート
        if own:
            comps = companies_from(rows, settings)
        if user and own:
            cands = [x for x in rows if x["login_id"] == user or (x["memo"] and user in x["memo"])]
            r = next((x for x in cands if not x["company"]), cands[0] if cands else None)
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
    if company:
        c = find_company(comps, company)
    elif len(comps) == 1:
        c = comps[0]
    elif comps:
        raise RuntimeError("どの会社に入るかを選んでください（--company 会社名）。会社："
                           + "、".join(f"{x['company']}（{x['code']}）" for x in comps))
    else:
        b = base_url(r["url"])
        url = b[1] if b else (r["url"] or settings["hitomane"]["base_url"])
        c = {"company": "", "code": (base_url(url) or ("",))[0], "url": url}
    if any(p.get("type") in ("anyone", "domain") for p in book.list_permissions()):
        raise RuntimeError("ログイン情報のあるスプレッドシートが「リンクを知っている全員」に共有されているため、"
                           "パスワードは使いません。共有を「制限付き」にしてから実行してください")
    if not r["password"]:
        raise RuntimeError(f"{sheet}シートの {r['login_id']} のパスワードが空欄です")
    return {"login_id": r["login_id"], "password": r["password"], "url": c["url"], "company": c["company"],
            "code": c["code"]}


def account_key(info: dict) -> str:
    """記録を分けるための会社の印（会社のコード。分からなければログインID）。"""
    return info.get("code") or info["login_id"]


def label(info: dict) -> str:
    """画面やログに出す「会社名（コード）」。"""
    return f"{info['company']}（{info.get('code', '')}）" if info.get("company") else info["url"]
