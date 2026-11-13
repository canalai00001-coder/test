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


def memo_filters(date_from: date | None, date_to: date | None, memo: str = "") -> list[str]:
    """テンプレート出力を何回に分けて、それぞれメモ欄に何を入れるか。

    期間を指定したときは月ごとに「-2610」「-2611」のように Q-mate 側で絞る（会社の全原稿を一度に書き出すと、
    件数が多い会社では Q-mate の出力が終わらないため）。期間の外の日は、取り出したあと row_filter で除く。
    """
    one = memo_filter(date_from, date_to, memo)
    if one or not (date_from and date_to) or date_from > date_to:
        return [one]
    months, y, m = [], date_from.year, date_from.month
    while (y, m) <= (date_to.year, date_to.month):
        months.append(f"-{y % 100:02d}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months if len(months) <= 6 else [""]


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


def make_chunks(src, out_dir: Path, label: str, update_type: str, status: str,
                chunk_rows: int = 10000, encoding: str = "utf-8", newline: str = "\r\n",
                keep=None) -> tuple[list[Path], int]:
    """取り出した CSV の更新種別とステータスを書き換え、chunk_rows 件ずつのファイルに分ける。

    ファイルは数百 MB になることがあるので、1行ずつ読みながら書き出す。UID のない行は消せないので飛ばす。
    src は1つのファイルか、ファイルのリスト（月ごとに分けて取り出したもの。同じ UID は1回だけ）。
    keep を渡すと、メモ列の値で keep が True を返す行だけを残す。
    戻り値は（分けたファイルのリスト, 取り下げる件数）。
    """
    csv.field_size_limit(2 ** 31 - 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths, total, seen = [], 0, set()
    writer = f = None
    for one in (src if isinstance(src, (list, tuple)) else [src]):
        with open(one, encoding="utf-8-sig", newline="") as fin:
            reader = csv.reader(fin)
            header = next(reader, None)
            if not header:
                continue
            names = [base_name(h) for h in header]
            uid, kind, st = names.index("UID"), names.index("更新種別"), names.index("ステータス")
            memo = names.index("メモ") if "メモ" in names else None
            for row in reader:
                if len(row) <= max(uid, kind, st) or not row[uid].strip() or row[uid] in seen:
                    continue
                if keep and not keep(row[memo] if memo is not None and memo < len(row) else ""):
                    continue
                seen.add(row[uid])
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
    status = export_status or td.get("export_status", "公開")
    cond = conditions(company, date_from, date_to, memo, status)
    if not dry_run:
        # さきほど同じ条件で「取り出しと件数の確認」をしていれば、Q-mate から取り出し直さずにそのファイルを使う
        found = find_prepared(cond)
        if found:
            log(f"{found['at'][11:16]} の確認で取り出したファイルを使います（取り出しを省きます）")
            return use_prepared(found["name"], settings, headed=headed, log=log)
    q = qmate_config(settings, company)  # その会社のログイン情報と CSV取込画面
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    label = f"取り下げ_{company}_{stamp}"
    out_dir = out_root / label
    cfg = dict(q, result_poll_times=td.get("result_poll_times", q.get("result_poll_times", 0)))
    up = QmateUploader(cfg, headless=not headed, out_dir=out_dir)

    queries = memo_filters(date_from, date_to, memo)
    query = "・".join(q for q in queries if q)
    span = describe(date_from, date_to)
    log(f"Q-mate のテンプレート出力で「{status}」の原稿を取り出します（{span}"
        f"{f'、メモ「{query}」で絞り込み' if query else ''}"
        f"{f'、{len(queries)}回に分けて取り出し' if len(queries) > 1 else ''}）")
    src = []
    for i, qy in enumerate(queries, start=1):
        if len(queries) > 1:
            log(f"取り出し {i}/{len(queries)}（メモ「{qy}」）")
        name = f"{label}_取り出し.csv" if len(queries) == 1 else f"{label}_取り出し_{i}.csv"
        src.append(up.export_template(status, out_dir / name, memo=qy, log=log))
    keep = row_filter(date_from, date_to, memo) if (date_from or date_to or memo) else None
    chunks, total = make_chunks(src, out_dir, label, td["update_type"], td["status"], td.get("chunk_rows", 10000),
                                keep=keep, **settings["csv"])
    log(f"取り下げる原稿: {total}件（{len(chunks)}ファイルに分けました）")
    result = {"company": company, "count": total, "files": [str(c) for c in chunks], "uploaded": 0,
              "span": span, "memo": query, "at": datetime.now().isoformat(timespec="seconds")}
    if dry_run:
        # 確認のときに取り出したファイルは残しておき、あとでそのまま取り下げられるようにする（use_prepared）
        if chunks:
            result["prepared"] = save_prepared(result, status, cond)
        return result
    if not chunks:
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


# ---------------------------------------------------------------- 確認で取り出したファイルを使って取り下げる
def _prepared_path() -> Path:
    from . import config
    return config.STATE_DIR / "takedown_prepared.json"


def _load_prepared() -> dict:
    import json
    p = _prepared_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_prepared_all(data: dict) -> None:
    import json
    p = _prepared_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def conditions(company: str, date_from: date | None, date_to: date | None, memo: str, status: str) -> dict:
    """取り下げの条件（確認のときと同じ条件か比べるため）。"""
    return {"company": company, "from": date_from.isoformat() if date_from else "",
            "to": date_to.isoformat() if date_to else "", "memo": memo or "", "status": status}


def find_prepared(cond: dict, today: date | None = None) -> dict | None:
    """今日、同じ条件で取り出して、まだ取り下げ終わっていない確認の結果（いちばん新しいもの）。"""
    return next((r for r in prepared_list(today) if r.get("cond") == cond), None)


def save_prepared(result: dict, status: str, cond: dict | None = None) -> str:
    """「取り出しと件数の確認だけ」の結果を残す。名前（取り出した日時と会社）を返す。"""
    data = _load_prepared()
    name = Path(result["files"][0]).parent.name
    data[name] = {"company": result["company"], "count": result["count"], "files": result["files"],
                  "span": result["span"], "memo": result["memo"], "status": status, "at": result["at"],
                  "cond": cond or {}, "uploaded": 0, "finished_at": ""}
    _save_prepared_all(data)
    return name


def prepared_list(today: date | None = None) -> list[dict]:
    """今日取り出して、まだ取り下げ終わっていないもの（新しい順）。"""
    today = today or date.today()
    out = []
    for name, r in _load_prepared().items():
        if r["finished_at"] or r["at"][:10] != today.isoformat():
            continue
        if not all(Path(f).exists() for f in r["files"]):
            continue
        out.append(dict(r, name=name))
    return sorted(out, key=lambda r: r["at"], reverse=True)


def use_prepared(name: str, settings: dict, headed: bool = False, log=print, today: date | None = None) -> dict:
    """確認のときに取り出して分けたファイルを、取り出し直さずにそのまま取り込んで取り下げる。

    取り出した日のうちだけ使える（日をまたぐと、そのあと入稿した原稿が入っていないため）。
    途中で失敗したときは、次は残りのファイルから続ける。
    """
    from .accounts import qmate_config
    from .uploader import QmateUploader

    today = today or date.today()
    data = _load_prepared()
    r = data.get(name)
    if r is None:
        raise RuntimeError(f"取り出し結果「{name}」が見つかりません")
    if r["finished_at"]:
        raise RuntimeError(f"この取り出し結果では {r['finished_at'][:16].replace('T', ' ')} に取り下げ済みです")
    if r["at"][:10] != today.isoformat():
        raise RuntimeError("取り出した日を過ぎているので使えません。もう一度「取り出しと件数の確認」からやり直してください")
    files = [Path(f) for f in r["files"]]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        raise RuntimeError(f"取り出したファイルが見つかりません（{'、'.join(missing)}）。取り出しからやり直してください")
    td = settings["takedown"]
    q = qmate_config(settings, r["company"])
    cfg = dict(q, result_poll_times=td.get("result_poll_times", q.get("result_poll_times", 0)))
    up = QmateUploader(cfg, headless=not headed, out_dir=files[0].parent)
    log(f"{r['at'][11:16]} に取り出した結果で取り下げます：{r['company']} / {r['span']}"
        f"{' / メモ「' + r['memo'] + '」' if r['memo'] else ''} / {r['count']}件（{len(files)}ファイル）")
    for i, path in enumerate(files, start=1):
        if i <= r["uploaded"]:
            log(f"取り下げ {i}/{len(files)}: {path.name}（前回取り込み済み）")
            continue
        log(f"取り下げ {i}/{len(files)}: {path.name}")
        res = up.upload(path, path.stem)
        if not res.ok:
            raise RuntimeError(f"取り下げの取り込みに失敗しました（{path.name}）: {res.message}。"
                               "もう一度押すと、残りのファイルから続けます")
        r["uploaded"] = i
        _save_prepared_all(data)
    r["finished_at"] = datetime.now().isoformat(timespec="seconds")
    _save_prepared_all(data)
    return {"company": r["company"], "count": r["count"], "files": r["files"], "uploaded": len(files),
            "span": r["span"], "memo": r["memo"], "at": r["finished_at"], "from_prepared": name}
