"""会社ごとの Q-mate のログイン情報。

いちばん先に見るのは、本体のスプレッドシートの「Q-mateログイン情報」シート
（会社名・ログインID・パスワード・CSV取込画面の URL）。
ただし、そのスプレッドシートが「リンクを知っている全員」などに共有されているあいだは、パスワードを使わずに止める。

次に、操作画面の「会社」タブで登録したもの。会社名・ログイン ID・CSV取込画面の URL は config/accounts.local.json に書く（GitHub には上げない。更新しても消えない）。
パスワードはファイルには書かず、Windows の「資格情報マネージャー」に保存する（keyring）。

登録していない会社でも、settings.json の qmate.company と同じ会社なら、
これまでどおり環境変数 QMATE_ID / QMATE_PASSWORD と qmate.upload_url を使う。
"""
import json
import os
import re

from . import config

SERVICE = "qmate_agent"
FILE = "accounts.local.json"
UPLOAD_URL = "https://m.q-mate.jp/job_offers/bulk_new?co={co}"
UPLOAD_URL_NO_CO = "https://m.q-mate.jp/job_offers/bulk_new"  # co が空欄のとき（ログイン後の画面から co を探す）


SHEET = "Q-mateログイン情報"
_sheet_cache: dict = {}


def _sheet_book(settings: dict):
    from .sheet import Spreadsheet
    return Spreadsheet(settings).book


def _is_public(book) -> bool:
    """リンクを知っている人・組織の全員が開ける共有になっているか。"""
    return any(p.get("type") in ("anyone", "domain") for p in book.list_permissions())


def sheet_status(settings: dict) -> dict:
    """{"rows": {会社名: {...}}, "public": bool, "error": str}。1回の実行のあいだは読み直さない。"""
    key = settings.get("spreadsheet_id", "")
    if key in _sheet_cache:
        return _sheet_cache[key]
    import gspread

    out = {"rows": {}, "public": False, "error": ""}
    try:
        book = _sheet_book(settings)
        try:
            values = book.worksheet(settings.get("accounts_sheet", SHEET)).get_all_values()
        except gspread.WorksheetNotFound:
            values = []
        out["rows"] = parse_sheet(values)
        if out["rows"]:
            out["public"] = _is_public(book)
    except Exception as e:
        out["error"] = str(e)
    _sheet_cache[key] = out
    return out


def parse_sheet(values: list) -> dict:
    """シートの表 → {会社名: {"login_id", "password", "co", "upload_url"}}。会社名とログインID のない行は飛ばす。"""
    if not values:
        return {}
    head = [str(h).strip() for h in values[0]]
    col = lambda *words: next((i for i, h in enumerate(head) if any(w in h for w in words)), None)
    ci, ii, pi, ui = col("会社"), col("ID", "ＩＤ"), col("パスワード"), col("URL", "co")
    if None in (ci, ii, pi, ui):
        raise RuntimeError(f"「{SHEET}」シートの見出しは「会社名・ログインID・パスワード・CSV取込画面のURL」にしてください")
    cell = lambda r, i: str(r[i]).strip() if i < len(r) else ""
    rows = {}
    for r in values[1:]:
        company, login_id = cell(r, ci), cell(r, ii)
        if not company or not login_id:
            continue
        co = parse_co(cell(r, ui)) if cell(r, ui) else ""
        rows[company] = {"login_id": login_id, "password": cell(r, pi), "co": co,
                         "upload_url": UPLOAD_URL.format(co=co) if co else UPLOAD_URL_NO_CO}
    return rows


def _path():
    return config.CONFIG_DIR / FILE


def load() -> dict:
    """{会社名: {"login_id", "co", "upload_url"}}"""
    p = _path()
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _keyring():
    try:
        import keyring
    except ImportError as e:
        raise RuntimeError("パスワードを保存する部品（keyring）が入っていません。"
                           "「更新」タブで最新にしたあと app.bat を開き直すか、pip install keyring を実行してください") from e
    return keyring


def parse_co(value: str) -> str:
    """「27859」でも CSV取込画面の URL（…bulk_new?co=27859）でも、co の番号を取り出す。"""
    v = (value or "").strip()
    m = re.search(r"[?&]co=(\d+)", v) or re.fullmatch(r"(\d+)", v)
    if not m:
        raise ValueError("Q-mate の会社番号が読み取れません。CSV取込画面の URL（…bulk_new?co=12345）か、co= の後ろの数字を入れてください")
    return m.group(1)


def save(company: str, login_id: str, co: str, password: str = "") -> dict:
    """登録・変更。password が空なら、保存済みのパスワードをそのまま使う。"""
    company, login_id = company.strip(), login_id.strip()
    if not company or not login_id:
        raise ValueError("会社名とログイン ID を入れてください")
    co = parse_co(co)
    data = load()
    if not password and company not in data:
        raise ValueError("パスワードを入れてください")
    if password:
        _keyring().set_password(SERVICE, company, password)
    data[company] = {"login_id": login_id, "co": co, "upload_url": UPLOAD_URL.format(co=co)}
    _save(data)
    return data[company]


def delete(company: str) -> None:
    data = load()
    if company not in data:
        raise ValueError(f"「{company}」は登録されていません")
    try:
        _keyring().delete_password(SERVICE, company)
    except Exception:
        pass  # パスワードが残っていなくても、登録は消す
    del data[company]
    _save(data)


def companies(settings: dict) -> list[str]:
    """入稿・取り下げに使える会社（登録した会社と、環境変数で使っている会社）。"""
    names = list(sheet_status(settings)["rows"])
    names += [n for n in load() if n not in names]
    q = settings["qmate"]
    if q.get("company") and q["company"] not in names and os.environ.get("QMATE_ID"):
        names.insert(0, q["company"])
    return names


def listing(settings: dict) -> list[dict]:
    """画面に出す一覧（パスワードは出さない。保存されているかどうかだけ）。"""
    out = []
    st = sheet_status(settings)
    for name, a in st["rows"].items():
        out.append({"company": name, "login_id": a["login_id"], "co": a["co"], "password": bool(a["password"]),
                    "source": "スプレッドシート" + ("（共有が公開のため使えません）" if st["public"] else "")})
    for name, a in load().items():
        if name in st["rows"]:
            continue
        try:
            has_pw = bool(_keyring().get_password(SERVICE, name))
        except Exception:
            has_pw = False
        out.append({"company": name, "login_id": a["login_id"], "co": a["co"], "password": has_pw, "source": "登録"})
    q = settings["qmate"]
    if q.get("company") and q["company"] not in {o["company"] for o in out} and os.environ.get("QMATE_ID"):
        co = re.search(r"co=(\d+)", q.get("upload_url", ""))
        out.insert(0, {"company": q["company"], "login_id": os.environ.get("QMATE_ID", ""), "co": co.group(1) if co else "",
                       "password": bool(os.environ.get("QMATE_PASSWORD")), "source": "環境変数（QMATE_ID）"})
    return out


def qmate_config(settings: dict, company: str) -> dict:
    """その会社で Q-mate に入るための設定（settings の qmate に、URL とログイン情報を足したもの）。"""
    q = dict(settings["qmate"])
    st = sheet_status(settings)
    if company in st["rows"]:
        if st["public"]:
            raise RuntimeError(f"本体のスプレッドシートが「リンクを知っている全員」に共有されているため、「{SHEET}」シートの"
                               "パスワードは使いません。共有を「制限付き」にしてから実行してください")
        a = st["rows"][company]
        if not a["password"]:
            raise RuntimeError(f"「{SHEET}」シートの {company} のパスワードが空欄です")
        q.update(upload_url=a["upload_url"], company=company, login_id=a["login_id"], password=a["password"])
        return q
    a = load().get(company)
    if a:
        pw = _keyring().get_password(SERVICE, company)
        if not pw:
            raise RuntimeError(f"「{company}」のパスワードが保存されていません。操作画面の「会社」タブで登録し直してください")
        q.update(upload_url=a["upload_url"], company=company, login_id=a["login_id"], password=pw)
        return q
    if company == q.get("company"):
        user, pw = os.environ.get("QMATE_ID"), os.environ.get("QMATE_PASSWORD")
        if user and pw:
            q.update(login_id=user, password=pw)
            return q
    if st["error"]:
        raise RuntimeError(f"「{company}」のログイン情報が見つかりません（「{SHEET}」シートも読めませんでした: {st['error']}）")
    raise RuntimeError(f"「{company}」の Q-mate のログイン情報が登録されていません。操作画面の「会社」タブで登録してください")


def login_problem(settings: dict, company: str) -> str:
    """その会社で Q-mate に入れないときの理由（入れるなら空）。実行の前に確かめる。"""
    try:
        qmate_config(settings, company)
    except RuntimeError as e:
        return str(e)
    return ""
