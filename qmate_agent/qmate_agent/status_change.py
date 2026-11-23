"""Q-mate にある原稿の掲載状況（ステータス）を、求人メモで指定して変える（例：終了 → 公開）。

スプレッドシートの「掲載状況変更」シートの行で行う。手順は取り下げと同じ形。
  1. CSV取込画面の「テンプレート出力」で、対象ステータスの原稿を CSV で取り出す
     （求人メモが少なければメモ欄に1つずつ入れて Q-mate 側で絞る。多ければ全件を1回で取り出す）
  2. 指定した求人メモを含む行だけを残し、更新種別を「更新」、ステータスを変更後のものに書き換える
     （取り下げと違い、原稿の中身はそのまま送り返す。空欄にすると内容が消えるおそれがあるため）
  3. 10,000 件ずつのファイルに分けて取り込む
"""
from datetime import datetime
from pathlib import Path

from .takedown import keep_memos, make_chunks

STATUSES = ("公開", "下書き", "終了")
EXPORT_STATUSES = ("全てのステータス", "公開", "下書き", "下書き＋公開", "終了")


def memo_matcher(memos: list[str]):
    """メモ列の値が、指定した求人メモのどれかを含むか。関数の found に、当たった求人メモが入る。"""
    def match(memo_value: str) -> bool:
        hit = [m for m in memos if m in memo_value]
        match.found.update(hit)
        return bool(hit)
    match.found = set()
    return match


def run(company: str, memos: list[str], to_status: str, settings: dict, out_root: Path,
        export_status: str = "", headed: bool = False, dry_run: bool = False, log=print) -> dict:
    """1社分の掲載状況変更。dry_run なら取り出しとファイル分けまでで止める。結果を dict で返す。"""
    from .accounts import qmate_config
    from .uploader import QmateUploader

    sc = settings.get("status_change", {})
    export_status = export_status or sc.get("export_status", "全てのステータス")
    if to_status not in STATUSES:
        raise RuntimeError(f"変更後ステータス「{to_status or '空欄'}」が読めません（{' / '.join(STATUSES)} のどれか）")
    if export_status not in EXPORT_STATUSES:
        raise RuntimeError(f"対象ステータス「{export_status}」が読めません（{' / '.join(EXPORT_STATUSES)} のどれか）")
    if not memos:
        raise RuntimeError("求人メモが空欄です。変えたい原稿の求人メモを入れてください")
    q = qmate_config(settings, company)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    label = f"掲載状況変更_{company}_{stamp}"
    out_dir = out_root / label
    cfg = dict(q, result_poll_times=sc.get("result_poll_times", q.get("result_poll_times", 0)))
    up = QmateUploader(cfg, headless=not headed, out_dir=out_dir)

    # 求人メモが少なければ1つずつ Q-mate 側で絞って取り出す（全件の取り出しは大きい会社で20分以上かかるため）
    queries = memos if len(memos) <= sc.get("max_memo_exports", 10) else [""]
    log(f"Q-mate のテンプレート出力で「{export_status}」の原稿を取り出します"
        f"（{f'求人メモごとに{len(queries)}回' if queries != [''] else '全件を1回で'}）")
    src = []
    for i, qy in enumerate(queries, start=1):
        if len(queries) > 1:
            log(f"取り出し {i}/{len(queries)}（{qy}）")
        name = f"{label}_取り出し.csv" if len(queries) == 1 else f"{label}_取り出し_{i}.csv"
        src.append(up.export_template(export_status, out_dir / name, memo=qy, log=log))
    match = memo_matcher(memos)
    chunks, total = make_chunks(src, out_dir, label, sc.get("update_type", "更新"), to_status,
                                sc.get("chunk_rows", 10000), keep=match, skip_status=to_status, **settings["csv"])
    missing = [m for m in memos if m not in match.found]
    log(f"「{to_status}」に変える原稿: {total}件（求人メモ {len(memos) - len(missing)}/{len(memos)}件が見つかりました。"
        "すでにそのステータスの原稿は飛ばします）")
    for m in missing:
        log(f"  見つからない求人メモ（対象ステータスに無いか、削除済み）: {m}")
    if not match.found:
        raise RuntimeError(f"指定した求人メモの原稿が、Q-mate の「{export_status}」に1件もありません"
                           "（削除（取り下げ）済みか、求人メモの書き違い）。削除した原稿は戻せないので、入稿し直してください")
    result = {"company": company, "count": total, "files": [str(c) for c in chunks], "uploaded": 0,
              "to": to_status, "missing": missing, "memos": len(memos),
              "at": datetime.now().isoformat(timespec="seconds")}
    if dry_run or not chunks:
        return result
    for i, path in enumerate(chunks, start=1):
        log(f"取り込み {i}/{len(chunks)}: {path.name}")
        r = up.upload(path, path.stem)
        if not r.ok:
            raise RuntimeError(f"掲載状況変更の取り込みに失敗しました（{path.name}）: {r.message}")
        result["uploaded"] = i
    return result


def merge_memos(texts) -> list[str]:
    """複数行の求人メモ欄を1つのリストにする（同じものは1回）。"""
    return list(dict.fromkeys(m for t in texts for m in keep_memos(t)))
