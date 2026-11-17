"""チェックと入稿の流れ（コマンドと操作画面の両方から使う）。

check：シート（または CSV）をチェックして output/<名前>/report.html と state/reviews.json に残す。
upload：check したときと中身が同じで、NG でなく、同じ内容をまだ入れていないときだけ、CSV にしてヒトマネに取り込む。
"""
import json
from datetime import datetime
from pathlib import Path

from . import config
from .checks import Manuscript, check_sheet, status_of
from .csv_export import read_csv, split_rows, to_csv_bytes
from .report import render


def load_state(name: str) -> dict:
    path = config.STATE_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_state(name: str, data: dict) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (config.STATE_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_manuscript(settings: dict, sheet: str | None = None, csv: str | None = None, book=None) -> Manuscript:
    if csv:
        return read_csv(Path(csv).read_bytes(), Path(csv).stem)
    from .sheet import Spreadsheet
    return Spreadsheet(settings, book).manuscript(sheet)


def check(ms: Manuscript, rules: dict) -> dict:
    sheet_issues, results = check_sheet(ms, rules)
    overall = status_of(sheet_issues + [i for r in results for i in r])
    out = config.OUTPUT_DIR / ms.name
    out.mkdir(parents=True, exist_ok=True)
    report = out / "report.html"
    report.write_text(render(ms.name, ms.rows, sheet_issues, results), encoding="utf-8")
    counts = {}
    for r in results:
        counts[status_of(r)] = counts.get(status_of(r), 0) + 1
    reviews = load_state("reviews.json")
    reviews[ms.name] = {"hash": ms.data_hash(), "status": overall, "rows": len(ms.rows), "counts": counts,
                        "checked_at": datetime.now().isoformat(timespec="seconds")}
    save_state("reviews.json", reviews)
    return {"name": ms.name, "status": overall, "rows": len(ms.rows), "counts": counts, "report": str(report),
            "sheet_issues": [i.to_dict() for i in sheet_issues],
            "issues": [[i.to_dict() for i in r] for r in results]}


def upload_problem(ms: Manuscript) -> str | None:
    """入稿してはいけない理由（なければ None）。"""
    rv = load_state("reviews.json").get(ms.name)
    if not rv:
        return "チェックをしていません。先にチェックしてください"
    if rv["hash"] != ms.data_hash():
        return "チェックのあとにシートの内容が変わっています。チェックをやり直してください"
    if rv["status"] == "NG":
        return "チェック結果が NG です。シートを直してチェックをやり直してください"
    done = load_state("uploaded.json").get(ms.name)
    if done and done.get("hash") == rv["hash"]:
        return f"同じ内容を {done['uploaded_at']} に入稿済みです"
    return None


def write_csvs(ms: Manuscript, settings: dict, rules: dict) -> list[Path]:
    """取り込む CSV を output/<名前>/ に書く（1万行ずつに分ける）。"""
    out = config.OUTPUT_DIR / ms.name
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for part in split_rows(ms, rules["max_rows_per_file"]):
        path = out / f"{part.name}.csv"
        path.write_bytes(to_csv_bytes(part, **settings["csv"]))
        paths.append(path)
    return paths


def total_note(total: int | None, rows: int, rules: dict) -> str:
    """入稿の前に見せる、全件数についての一言。"""
    if total is None:
        return "募集管理の全件数を読めませんでした"
    limit = rules["total_limit"]
    note = f"募集管理の全件数は {total:,}件です（上限 {limit:,}件）"
    if total + rows > limit:
        note += (f"。新しい募集番号が多いと、入れる {rows:,}件を足して上限を超えます"
                 "（同じ募集番号は上書きなので増えません）。先に取り下げるか確かめてください")
    return note


def record_upload(ms: Manuscript, results: list) -> None:
    if results and all(r.ok for r in results):
        uploaded = load_state("uploaded.json")
        uploaded[ms.name] = {"hash": ms.data_hash(), "rows": len(ms.rows),
                             "uploaded_at": datetime.now().isoformat(timespec="seconds"),
                             "files": [r.file for r in results]}
        save_state("uploaded.json", uploaded)


def save_total(login_id: str, total: int | None) -> None:
    """最後に読んだ募集管理の全件数を覚えておく（操作画面の入稿タブに出す）。読めなかったときは書かない。"""
    if total is None:
        return
    save_state("total.json", {"login_id": login_id, "total": total,
                              "at": datetime.now().isoformat(timespec="seconds")})


def last_total() -> dict:
    return load_state("total.json")
