"""会社ごとの Q-mate のログイン情報。

会社名・ログイン ID・CSV取込画面の URL は config/accounts.local.json に書く（GitHub には上げない。更新しても消えない）。
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
    names = list(load())
    q = settings["qmate"]
    if q.get("company") and q["company"] not in names and os.environ.get("QMATE_ID"):
        names.insert(0, q["company"])
    return names


def listing(settings: dict) -> list[dict]:
    """画面に出す一覧（パスワードは出さない。保存されているかどうかだけ）。"""
    out = []
    for name, a in load().items():
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
    raise RuntimeError(f"「{company}」の Q-mate のログイン情報が登録されていません。操作画面の「会社」タブで登録してください")
