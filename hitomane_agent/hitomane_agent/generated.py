"""ツールで作った原稿（GAS の③の代わりに generator で作ったもの）の置き場所。

  output/生成/<名前>/
    manuscript.json  原稿（見出し＋行）と予約行ごとの区切り
    meta.json        どの予約から作ったか・会社・作った日時・使用履歴に書く職種名と仕事内容の件数・入稿したか

名前は GAS の出力シート名の「ヒトマネ出力_」を「ツール_」に変えたもの（例：ツール_新_G1_canal benefits株式会社_5半導体_20261120）。
同じ予約をもう一度作ると上書きする。スプレッドシートには書かない。
"""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from . import config
from .checks import Manuscript
from .headers import NEW_FORMAT

PREFIX = "ツール_"


def root() -> Path:
    return config.OUTPUT_DIR / "生成"


def name_for(gas_name: str) -> str:
    return PREFIX + gas_name.removeprefix("ヒトマネ出力_")


def gas_name_for(name: str) -> str:
    return "ヒトマネ出力_" + name.removeprefix(PREFIX)


def _dir(name: str) -> Path:
    """画面から来た名前を、生成のフォルダに限って開く（../ などでほかの場所を開かせない）。"""
    if not name.startswith(PREFIX) or re.search(r'[\\/:*?"<>|]|\.\.', name):
        raise ValueError("ツールで作った原稿の名前が正しくありません")
    return root() / name


def save(result, meta: dict) -> str:
    """generator.GroupResult を保存して名前を返す。"""
    name = name_for(result.name)
    d = _dir(name)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    segments, n = [], 0
    for tc in result.title_counts:
        segments.append(n)
        n += sum(tc.values())
    headers = getattr(result, "headers", None) or NEW_FORMAT
    rows = [r if isinstance(r, list) else [r[h] for h in headers] for r in result.rows]
    (d / "manuscript.json").write_text(json.dumps({"headers": headers, "segments": segments, "rows": rows},
                                                  ensure_ascii=False), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({
        **meta, "name": name, "gas_name": result.name, "group": result.group_id, "company": result.company,
        "category": result.category, "rows": len(result.rows),
        "sheet_rows": [t.sheet_row for t in result.targets if f"行{t.sheet_row}（旧FMT）" not in result.skipped],
        "skipped": result.skipped, "title_counts": result.title_counts, "content_counts": result.content_counts,
        "loc_records": getattr(result, "loc_records", []),
        "created_at": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False, indent=1), encoding="utf-8")
    return name


def exists(name: str) -> bool:
    try:
        return (_dir(name) / "manuscript.json").exists()
    except ValueError:
        return False


def load(name: str) -> Manuscript:
    d = _dir(name)
    if not (d / "manuscript.json").exists():
        raise FileNotFoundError(f"ツールで作った原稿「{name}」が見つかりません")
    data = json.loads((d / "manuscript.json").read_text(encoding="utf-8"))
    return Manuscript(name, [data["headers"]] + data["rows"], segments=data.get("segments"))


def meta(name: str) -> dict:
    return json.loads((_dir(name) / "meta.json").read_text(encoding="utf-8"))


def listing() -> list[dict]:
    if not root().exists():
        return []
    out = []
    for d in sorted(root().iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if (d / "meta.json").exists() and d.name.startswith(PREFIX):
            m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            out.append({k: m.get(k) for k in ("name", "gas_name", "group", "company", "category", "rows", "sheet_rows",
                                              "skipped", "created_at")})
    return out
