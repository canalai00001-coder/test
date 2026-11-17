"""取り下げ：取り出した原稿を絞り込み、開始日・終了日を2年前、ステータスを「非掲載」に書き換える。

ヒトマネは、終了日が未来のままだと非掲載にしても残り続ける（入れた日から1年後が終了日）。
開始日・終了日を2年前にしておくと表示されず、放っておくと削除扱いになる（利用者の手作業と同じやり方）。

「確認だけ」で作ったファイルは state/takedown_prepared.json に残し、同じ日・同じアカウント・同じ条件の
「取り下げる」ではそのファイルを使う（取り出しを省く）。
"""
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import config
from .checks import Manuscript, to_date
from .headers import NEW_FORMAT


@dataclass(frozen=True)
class Conditions:
    start_from: date
    start_to: date
    posted_only: bool = True

    def label(self) -> str:
        return f"{self.start_from:%Y%m%d}-{self.start_to:%Y%m%d}"

    def describe(self) -> str:
        return (f"掲載開始日 {self.start_from:%Y/%m/%d}〜{self.start_to:%Y/%m/%d}"
                + ("・掲載のみ" if self.posted_only else ""))


def parse_day(s: str) -> date:
    d = to_date(s)
    if d is None:
        raise ValueError(f"日付は 2026/11/16 の形で入れてください（「{s}」）")
    return d


def two_years_ago(today: date) -> date:
    try:
        return today.replace(year=today.year - 2)
    except ValueError:  # 2/29
        return today.replace(year=today.year - 2, day=28)


@dataclass
class Rewritten:
    manuscript: Manuscript
    skipped: dict = field(default_factory=dict)
    new_date: str = ""


def rewrite(ms: Manuscript, cond: Conditions, branch: dict, today: date) -> Rewritten:
    """取り出した原稿（新フォーマット）のうち、条件に合う行だけを書き換えて返す。"""
    if ms.headers != NEW_FORMAT:
        raise ValueError("取り出した CSV の見出しが新フォーマットと違います。取り下げを止めます")
    new = f"{two_years_ago(today):%Y/%m/%d}"
    i_start, i_end, i_status = (ms.headers.index(c) for c in ("開始日", "終了日", "ステータス"))
    i_code, i_name = ms.headers.index("拠点コード"), ms.headers.index("拠点")
    kept, skipped = [], {}

    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    for r in ms.raw_rows:
        start = to_date(r[i_start])
        if r[i_code].strip() != branch["code"] or r[i_name].strip() != branch["name"]:
            skip("拠点が違う")
        elif cond.posted_only and r[i_status].strip() != "掲載":
            skip("掲載でない")
        elif start is None or not (cond.start_from <= start <= cond.start_to):
            skip("期間の外")
        else:
            r = list(r)
            r[i_start] = r[i_end] = new
            r[i_status] = "非掲載"
            kept.append(r)
    return Rewritten(Manuscript(ms.name, [ms.headers] + kept), skipped, new)


# ---- 確認だけ のファイル ----

def _key(account: str, cond: Conditions, today: date) -> str:
    """account は会社のコード（accounts.account_key）。会社が違えば別の確認になる。"""
    return f"{today:%Y-%m-%d}|{account}|{cond.label()}|{int(cond.posted_only)}"


def save_prepared(account: str, cond: Conditions, data: dict, today: date) -> None:
    path = config.STATE_DIR / "takedown_prepared.json"
    all_ = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    all_ = {k: v for k, v in all_.items() if k.startswith(f"{today:%Y-%m-%d}|")}  # 前の日のものは消す
    all_[_key(account, cond, today)] = {**data, "conditions": cond.describe(), "account": account,
                                         "prepared_at": datetime.now().isoformat(timespec="seconds")}
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(all_, ensure_ascii=False, indent=2), encoding="utf-8")


def find_prepared(account: str, cond: Conditions, today: date) -> dict | None:
    path = config.STATE_DIR / "takedown_prepared.json"
    if not path.exists():
        return None
    p = json.loads(path.read_text(encoding="utf-8")).get(_key(account, cond, today))
    if not p or not all(Path(f).exists() for f in p.get("files", [])):
        return None
    return p


def prepared_list(today: date, account: str | None = None) -> list[dict]:
    path = config.STATE_DIR / "takedown_prepared.json"
    if not path.exists():
        return []
    out = []
    for k, v in json.loads(path.read_text(encoding="utf-8")).items():
        if not k.startswith(f"{today:%Y-%m-%d}|") or (account is not None and k.split("|")[1] != account):
            continue
        a, b = k.split("|")[2].split("-")  # 操作画面の「この期間を入れる」用
        out.append({**v, "from": f"{a[:4]}/{a[4:6]}/{a[6:]}", "to": f"{b[:4]}/{b[4:6]}/{b[6:]}"})
    return out


def record(entry: dict) -> None:
    path = config.STATE_DIR / "takedown.json"
    history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    history.append({**entry, "at": datetime.now().isoformat(timespec="seconds")})
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def as_dict(cond: Conditions) -> dict:
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in asdict(cond).items()}
