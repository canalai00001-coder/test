"""使い方:
    python -m qmate_agent check            # シートを読んでチェック → output/report.html
    python -m qmate_agent post --dry-run   # 承認済みを入力・照合まで（保存しない）
    python -m qmate_agent post             # 承認済みを Q-mate に保存
    python -m qmate_agent login            # ブラウザで手動ログインしてセッション保存
"""
import argparse
import json
import sys
from datetime import datetime

from . import config
from .report import render
from .sheet import Sheet
from .validate import build_job, check_duplicates, job_hash, run_rules


def _load_state(name: str) -> dict:
    path = config.STATE_DIR / name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_state(name: str, data: dict) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (config.STATE_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _status(issues) -> str:
    if any(i.severity == "error" for i in issues):
        return "NG"
    if any(i.severity == "warning" for i in issues):
        return "要確認"
    return "OK"


def _open_sheet(args, sheet_cfg):
    return Sheet(sheet_cfg, source="csv" if args.csv else None, csv_path=args.csv)


def cmd_check(args) -> int:
    sheet_cfg, fcfg = config.load("sheet.json"), config.load("fields.json")
    fields, rules = fcfg["fields"], fcfg["rules"]
    labels = {f["key"]: f["label"] for f in fields}
    sheet = _open_sheet(args, sheet_cfg)
    rows = sheet.rows()
    jobs = [build_job(r, fields) for r in rows]
    dupes = check_duplicates(jobs)

    reviewer = None
    if not args.no_ai:
        from .ai_review import AIReviewer
        reviewer = AIReviewer()

    reviews = _load_state("reviews.json")
    results = []
    for row, job in zip(rows, jobs):
        issues = run_rules(job, fields, rules) + dupes.get(job.get("job_no", ""), [])
        summary = ""
        if reviewer:
            try:
                ai_issues, summary = reviewer.review(job, labels, issues)
                issues += ai_issues
            except Exception as e:
                from .validate import Issue
                issues.append(Issue("error", "general", f"AIチェックに失敗しました: {e}", "ai"))
        status = _status(issues)
        results.append({"row": row.row_number, "job": job, "issues": issues, "status": status, "summary": summary})
        reviews[job.get("job_no") or f"row{row.row_number}"] = {
            "hash": job_hash(job), "status": status, "ai": reviewer is not None,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }
        wb = sheet_cfg.get("write_back", {})
        sheet.write(row, wb.get("check_status_column"), status)
        sheet.write(row, wb.get("check_detail_column"),
                    "\n".join(f"[{i.severity}] {labels.get(i.field, i.field)}: {i.message}" for i in issues))
        print(f"{row.row_number}行目 {job.get('job_no', '')}: {status}（{len(issues)}件）")

    _save_state("reviews.json", reviews)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = config.OUTPUT_DIR / "report.html"
    out.write_text(render(results, labels), encoding="utf-8")
    print(f"\nレポート: {out}")
    print(f"内容を確認し、投稿してよい行の「{sheet_cfg['approval_column']}」列に "
          f"{sheet_cfg['approval_value']} を入れてから post を実行してください。")
    return 0


def select_targets(rows, jobs, sheet_cfg, fields, rules, reviews, posted, require_ai=True):
    """承認済みで、承認後に内容が変わっておらず、まだ投稿していない行だけを選ぶ。"""
    targets, skipped = [], []
    for row, job in zip(rows, jobs):
        no = job.get("job_no") or f"row{row.row_number}"
        if row.get(sheet_cfg["approval_column"]) != sheet_cfg["approval_value"]:
            continue
        rev, h = reviews.get(no), job_hash(job)
        if not rev:
            skipped.append((row, job, "チェック未実施です。先に check を実行してください"))
        elif rev["hash"] != h:
            skipped.append((row, job, "チェック後にシートの内容が変わっています。check をやり直してください"))
        elif require_ai and not rev.get("ai"):
            skipped.append((row, job, "AIチェックなしで承認されています。--no-ai なしで check してください"))
        elif rev["status"] == "NG":
            skipped.append((row, job, "チェック結果が NG のままです"))
        elif any(i.severity == "error" for i in run_rules(job, fields, rules)):
            skipped.append((row, job, "ルールチェックでエラーがあります"))
        elif posted.get(no, {}).get("hash") == h:
            skipped.append((row, job, "同じ内容で投稿済みです"))
        else:
            targets.append((row, job))
    return targets, skipped


def cmd_post(args) -> int:
    from .poster import QmatePoster

    sheet_cfg, fcfg, form_cfg = config.load("sheet.json"), config.load("fields.json"), config.load("qmate_form.json")
    fields, rules = fcfg["fields"], fcfg["rules"]
    sheet = _open_sheet(args, sheet_cfg)
    rows = sheet.rows()
    jobs = [build_job(r, fields) for r in rows]
    reviews, posted = _load_state("reviews.json"), _load_state("posted.json")
    targets, skipped = select_targets(rows, jobs, sheet_cfg, fields, rules, reviews, posted,
                                      require_ai=not args.allow_no_ai)

    for row, job, reason in skipped:
        print(f"スキップ {row.row_number}行目 {job.get('job_no', '')}: {reason}")
    if not targets:
        print("投稿対象がありません")
        return 0
    mode = "入力・照合のみ（保存しない）" if args.dry_run else form_cfg.get("submit_mode", "draft")
    print(f"\n投稿対象 {len(targets)}件 / モード: {mode}")
    for row, job in targets:
        print(f"  {row.row_number}行目 {job.get('job_no', '')} {job.get('title', '')}")
    if not args.yes and input("実行しますか？ [y/N] > ").strip().lower() != "y":
        print("中止しました")
        return 1

    by_no = {id(job): row for row, job in targets}
    post_col = sheet_cfg.get("write_back", {}).get("post_status_column")

    def on_result(job, r):
        row = by_no[id(job)]
        no = job.get("job_no") or f"row{row.row_number}"
        print(f"{'成功' if r.ok else '失敗'} {row.row_number}行目 {no}: {r.message}")
        for m in r.mismatches:
            print(f"    {m['field']}: 期待「{m['expected']}」 / 画面「{m['actual']}」")
        if r.ok and not args.dry_run:
            posted[no] = {"hash": job_hash(job), "posted_at": datetime.now().isoformat(timespec="seconds"),
                          "url": r.url, "mode": form_cfg.get("submit_mode", "draft")}
            _save_state("posted.json", posted)
        sheet.write(row, post_col, f"{datetime.now():%m/%d %H:%M} {r.message}")

    poster = QmatePoster(form_cfg, headless=not args.headed)
    results = poster.run([job for _, job in targets], dry_run=args.dry_run, on_result=on_result)
    return 0 if all(r.ok for r in results) else 2


def cmd_login(args) -> int:
    from .poster import QmatePoster
    QmatePoster(config.load("qmate_form.json")).save_login_manually()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qmate_agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="シートを読み込んでチェックし、レポートを作る")
    c.add_argument("--csv", help="スプレッドシートの代わりに CSV を読む")
    c.add_argument("--no-ai", action="store_true", help="AIチェックを省く（ルールチェックのみ）")
    c.set_defaults(func=cmd_check)

    p = sub.add_parser("post", help="承認済みの求人を Q-mate に入力する")
    p.add_argument("--csv", help="スプレッドシートの代わりに CSV を読む")
    p.add_argument("--dry-run", action="store_true", help="入力と照合だけ行い、保存しない")
    p.add_argument("--headed", action="store_true", help="ブラウザを表示して動かす")
    p.add_argument("--yes", action="store_true", help="実行前の確認を省く")
    p.add_argument("--allow-no-ai", action="store_true", help="AIチェックなしの承認も投稿対象にする")
    p.set_defaults(func=cmd_post)

    lg = sub.add_parser("login", help="手動ログインしてセッションを保存する")
    lg.set_defaults(func=cmd_login)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
