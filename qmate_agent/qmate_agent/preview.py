"""テスト（入稿しないで作る）の結果。

入稿予定表の1行分を、入稿も使用履歴の記録もしないで作ってチェックし、output/テスト/ に残す。
操作画面で指摘のある項目を書き直し（書き直すたびにチェックし直す）、問題がなければその内容のまま入稿できる。

  output/テスト/<入稿予定表の行>行目_<日時>/
    manuscript.json  原稿（見出し＋行）。書き直すとここが変わる
    meta.json        どの予約から作ったか・入稿先の会社・応募先メール・使用履歴に書く職種名・入稿したか
    issues.json      行ごとの指摘
"""
import json
import re
from datetime import datetime
from pathlib import Path

from . import config
from .checks import Manuscript, base_name, check_sheet, status_of


def root() -> Path:
    return config.OUTPUT_DIR / "テスト"


def _dir(name: str) -> Path:
    """画面から来た名前を、テスト結果のフォルダに限って開く（../ などでほかの場所を開かせない）。"""
    if not re.fullmatch(r"\d+行目_\d{8}_\d{6}", name or ""):
        raise ValueError("テスト結果の名前が正しくありません")
    d = root() / name
    if not (d / "meta.json").exists():
        raise ValueError(f"テスト結果「{name}」が見つかりません")
    return d


def _read(d: Path, name: str):
    return json.loads((d / name).read_text(encoding="utf-8"))


def _write(d: Path, name: str, data) -> None:
    (d / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def save(meta: dict, ms: Manuscript) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"{meta['row']}行目_{stamp}"
    d = root() / name
    d.mkdir(parents=True, exist_ok=True)
    _write(d, "manuscript.json", {"name": ms.name, "table": [ms.headers] + ms.raw_rows})
    _write(d, "meta.json", dict(meta, created_at=datetime.now().isoformat(timespec="seconds"), uploaded_at=""))
    recheck(name)
    return name


def manuscript(name: str) -> Manuscript:
    m = _read(_dir(name), "manuscript.json")
    return Manuscript(m["name"], m["table"])


def meta(name: str) -> dict:
    return _read(_dir(name), "meta.json")


def mark_uploaded(name: str, text: str) -> None:
    d = _dir(name)
    m = _read(d, "meta.json")
    m["uploaded_at"] = datetime.now().isoformat(timespec="seconds")
    m["upload_result"] = text
    _write(d, "meta.json", m)


def recheck(name: str) -> dict:
    """ルールチェック（AI チェックはしない）をして issues.json に書く。"""
    d = _dir(name)
    m = _read(d, "meta.json")
    ms = manuscript(name)
    rules = config.load("rules.json")
    ms.fill_blanks(rules.get("blank_defaults", {}))
    results = check_sheet(ms, rules, one_segment=True, company=m.get("company_info"))
    issues = [[i.to_dict() for i in r] for r in results]
    _write(d, "issues.json", issues)
    flat = [x for r in results for x in r]
    m["status"] = status_of(flat)
    m["counts"] = {s: sum(1 for r in results if status_of(r) == s) for s in ("NG", "要確認", "OK")}
    _write(d, "meta.json", m)
    return m


def edit(name: str, row: int, column: str, value: str) -> dict:
    """row 行目（0始まり）の column（見出しの「|必須」を除いた名前）を書き直して、チェックし直す。"""
    d = _dir(name)
    m = _read(d, "manuscript.json")
    table = m["table"]
    if not 0 <= row < len(table) - 1:
        raise ValueError("行が見つかりません")
    cols = [i for i, h in enumerate(table[0]) if base_name(h) == column]
    if not cols:
        raise ValueError(f"列「{column}」が見つかりません")
    r = table[row + 1]
    r += [""] * (len(table[0]) - len(r))
    r[cols[0]] = value  # 同じ見出しが2つある列（給与形態など）は、チェックと同じく最初の列
    _write(d, "manuscript.json", m)
    return recheck(name)


def listing() -> list[dict]:
    out = []
    if not root().exists():
        return out
    for d in sorted(root().iterdir(), reverse=True):
        if (d / "meta.json").exists():
            m = _read(d, "meta.json")
            out.append({"name": d.name, "row": m["row"], "company": m["company"], "category": m["category"],
                        "commute": m["commute"], "night": m.get("night", ""), "count": m.get("count", 0),
                        "created_at": m["created_at"], "status": m.get("status", ""), "counts": m.get("counts", {}),
                        "uploaded_at": m.get("uploaded_at", ""), "upload_result": m.get("upload_result", "")})
    return out


# 画面の一覧で、どの原稿か分かるように出す列
SUMMARY_COLUMNS = ("勤務地：都道府県", "勤務地：市区町村", "職種名", "給与_下限", "給与_上限")


def detail(name: str, only_issues: bool = True, limit: int = 300) -> dict:
    """画面に出す中身。指摘のある行（only_issues なら）と、その行の指摘のある列の値。"""
    d = _dir(name)
    ms = manuscript(name)
    issues = _read(d, "issues.json")
    rows = []
    for i, (r, iss) in enumerate(zip(ms.rows, issues)):
        if only_issues and not iss:
            continue
        cols = list(dict.fromkeys(x["column"] for x in iss))
        rows.append({"index": i, "summary": {c: r.get(c, "") for c in SUMMARY_COLUMNS},
                     "issues": iss, "values": {c: r.get(c, "") for c in cols if c in r}})
        if len(rows) >= limit:
            break
    columns = list(dict.fromkeys(base_name(h) for h in ms.headers))
    return {"meta": _read(d, "meta.json"), "rows": rows, "total": len(ms.rows), "columns": columns}


def cell(name: str, row: int, column: str) -> str:
    ms = manuscript(name)
    if not 0 <= row < len(ms.rows):
        raise ValueError("行が見つかりません")
    return ms.rows[row].get(column, "")
