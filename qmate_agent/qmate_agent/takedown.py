"""前回入稿した原稿を Q-mate から取り下げる（削除する）。

Q-mate は1つの会社のアカウントに載せられる原稿の数に上限があるので、新しい原稿を入れる前に、
今載っている原稿を消す。手順は、これまで手作業でしていたのと同じ。
  1. CSV取込画面の「テンプレート出力」で、今の「公開」の原稿を CSV で取り出す
  2. 更新種別（B列）を「削除」、ステータス（C列）を「終了」に書き換える
  3. Q-mate は1回に 10,000 件までしか取り込めないので、10,000 件ずつのファイルに分ける
  4. 分けたファイルを1つずつ取り込む
"""
import csv
import re
from datetime import date, datetime
from pathlib import Path

from .checks import base_name


def memo_date(memo: str) -> date | None:
    """求人メモ「22-261104-1-1-7A-…」の2番目（作成日 YYMMDD）を日付にする。読めなければ None。"""
    parts = (memo or "").split("-")
    if len(parts) < 2 or not re.fullmatch(r"\d{6}", parts[1].strip()):
        return None
    try:
        return datetime.strptime(parts[1].strip(), "%y%m%d").date()
    except ValueError:
        return None


def memo_filter(date_from: date | None, date_to: date | None, memo: str = "") -> str:
    """Q-mate のテンプレート出力のメモ欄に入れる文字。1日だけなら「-261104-」で Q-mate 側で絞る。"""
    if memo:
        return memo
    if date_from and date_from == date_to:
        return f"-{date_from:%y%m%d}-"
    return ""


def row_filter(date_from: date | None, date_to: date | None, memo: str = ""):
    """取り出した行のうち、取り下げる行かどうかを決める関数（メモ列の値を受け取る）。

    作成日を指定したときは、メモの作成日が読めない行と期間外の行は取り下げない。
    """
    def keep(memo_value: str) -> bool:
        if memo and memo not in memo_value:
            return False
        if date_from or date_to:
            d = memo_date(memo_value)
            if d is None or (date_from and d < date_from) or (date_to and d > date_to):
                return False
        return True
    return keep


def make_chunks(src: Path, out_dir: Path, label: str, update_type: str, status: str,
                chunk_rows: int = 10000, encoding: str = "utf-8", newline: str = "\r\n",
                keep=None) -> tuple[list[Path], int]:
    """取り出した CSV の更新種別とステータスを書き換え、chunk_rows 件ずつのファイルに分ける。

    ファイルは数百 MB になることがあるので、1行ずつ読みながら書き出す。UID のない行は消せないので飛ばす。
    keep を渡すと、メモ列の値で keep が True を返す行だけを残す。
    戻り値は（分けたファイルのリスト, 取り下げる件数）。
    """
    csv.field_size_limit(2 ** 31 - 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths, total = [], 0
    writer = f = None
    with open(src, encoding="utf-8-sig", newline="") as fin:
        reader = csv.reader(fin)
        header = next(reader, None)
        if not header:
            return [], 0
        names = [base_name(h) for h in header]
        uid, kind, st = names.index("UID"), names.index("更新種別"), names.index("ステータス")
        memo = names.index("メモ") if "メモ" in names else None
        for row in reader:
            if len(row) <= max(uid, kind, st) or not row[uid].strip():
                continue
            if keep and not keep(row[memo] if memo is not None and memo < len(row) else ""):
                continue
            if total % chunk_rows == 0:
                if f:
                    f.close()
                path = out_dir / f"{label}_{len(paths) + 1}.csv"
                f = open(path, "w", encoding=encoding, newline="")
                writer = csv.writer(f, lineterminator=newline, quoting=csv.QUOTE_MINIMAL)
                writer.writerow(header)
                paths.append(path)
            row[kind], row[st] = update_type, status
            writer.writerow(row)
            total += 1
    if f:
        f.close()
    return paths, total


def run(company: str, settings: dict, out_root: Path, headed: bool = False, dry_run: bool = False,
        log=print, date_from: date | None = None, date_to: date | None = None, memo: str = "",
        export_status: str | None = None) -> dict:
    """1社分の取り下げ。dry_run なら取り出しとファイル分けまでで止める。結果を dict で返す。

    date_from / date_to：求人メモの作成日がこの期間の原稿だけを取り下げる（どちらも省略で全期間）。
    memo：メモにこの文字を含む原稿だけ（Q-mate のメモ欄にも入れて絞る）。
    """
    from .uploader import QmateUploader
    from .accounts import qmate_config

    td = settings["takedown"]
    q = qmate_config(settings, company)  # その会社のログイン情報と CSV取込画面
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    label = f"取り下げ_{company}_{stamp}"
    out_dir = out_root / label
    cfg = dict(q, result_poll_times=td.get("result_poll_times", q.get("result_poll_times", 0)))
    up = QmateUploader(cfg, headless=not headed, out_dir=out_dir)

    status = export_status or td["export_status"]
    query = memo_filter(date_from, date_to, memo)
    span = describe(date_from, date_to)
    log(f"Q-mate のテンプレート出力で「{status}」の原稿を取り出します（{span}"
        f"{f'、メモ「{query}」で絞り込み' if query else ''}）")
    src = up.export_template(status, out_dir / f"{label}_取り出し.csv", memo=query)
    keep = row_filter(date_from, date_to, memo) if (date_from or date_to or memo) else None
    chunks, total = make_chunks(src, out_dir, label, td["update_type"], td["status"], td.get("chunk_rows", 10000),
                                keep=keep, **settings["csv"])
    log(f"取り下げる原稿: {total}件（{len(chunks)}ファイルに分けました）")
    result = {"company": company, "count": total, "files": [str(c) for c in chunks], "uploaded": 0,
              "span": span, "memo": query, "at": datetime.now().isoformat(timespec="seconds")}
    if dry_run or not chunks:
        return result
    for i, path in enumerate(chunks, start=1):
        log(f"取り下げ {i}/{len(chunks)}: {path.name}")
        r = up.upload(path, path.stem)
        if not r.ok:
            raise RuntimeError(f"取り下げの取り込みに失敗しました（{path.name}）: {r.message}")
        result["uploaded"] = i
    return result


def describe(date_from: date | None, date_to: date | None) -> str:
    if not date_from and not date_to:
        return "作成日：全期間"
    if date_from == date_to:
        return f"作成日：{date_from:%Y/%m/%d}"
    return f"作成日：{f'{date_from:%Y/%m/%d}' if date_from else ''}〜{f'{date_to:%Y/%m/%d}' if date_to else ''}"
