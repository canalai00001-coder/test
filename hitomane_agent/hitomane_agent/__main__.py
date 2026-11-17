"""ヒトマネ入稿ツールのコマンド。

  python -m hitomane_agent companies                                    会社の一覧（ログイン情報シートの会社の行）
  python -m hitomane_agent survey --company 会社 [--headed] [--sample [募集番号]]   管理画面の画面調査
  python -m hitomane_agent login (--company 会社 | --all)               ログインの確認と募集管理の全件数・拠点
  python -m hitomane_agent list                                         出力シートの一覧とチェックの状態
  python -m hitomane_agent check (--sheet 名前 | --csv パス)            入稿前のチェック
  python -m hitomane_agent upload --company 会社 (--sheet 名前 | --csv パス) [--yes] [--dry-run]   ヒトマネに取り込む
  python -m hitomane_agent takedown --company 会社 --from 2026/10/01 --to 2026/10/31 [--prepare-only] [--yes]   取り下げ

ヒトマネは会社ごとに管理画面の URL が違う（ID・パスワードは同じ）。--company は会社名・会社のコード（o3h3 など）・会社名の一部のどれでもよい。
会社が1社しかないときと、settings.local.json に "company" を書いたときは省ける。
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import accounts, config, workflow


def _settings(args) -> dict:
    settings = config.load("settings.json")
    if getattr(args, "user", None):
        settings["login_user"] = args.user
    return settings


def _info(args, settings) -> dict:
    return accounts.login_info(settings, company=getattr(args, "company", None))


def cmd_companies(args) -> int:
    cs = accounts.companies(_settings(args))
    if not cs:
        print("ログイン情報シートに会社の行がありません（会社名とヒトマネの URL の入った行を足してください）")
    for c in cs:
        print(f"{c['company']}  {c['code']}  {c['url']}")
    return 0


def cmd_survey(args) -> int:
    from .survey import run_survey

    settings = _settings(args)
    try:
        info = _info(args, settings)
    except Exception as e:
        print(f"ログイン情報を読めませんでした: {e}")
        return 1
    out = config.OUTPUT_DIR / f"画面調査_{info.get('code') or 'x'}_{datetime.now():%Y%m%d_%H%M}"
    h = settings["hitomane"]
    print(f"{accounts.label(info)} の管理画面を {info['login_id']} で調べます（{info['url']}）。取り込み・取り下げはしません")
    res = run_survey(info, out, headed=args.headed, sample=args.sample or "",
                     poll_interval_ms=h["poll_interval_ms"], export_poll_times=h["export_poll_times"],
                     timeout_ms=h["timeout_ms"])
    ok = sum(1 for s in res["steps"] if s["ok"])
    print(f"\n{len(res['steps'])}画面中 {ok}画面を保存しました")
    print(f"output\\{out.name} フォルダをまとめて（ZIP にして）送ってください：{out}")
    return 0 if ok == len(res["steps"]) else 2


def cmd_list(args) -> int:
    from .sheet import Spreadsheet

    names = Spreadsheet(_settings(args)).output_sheet_names()
    reviews, uploaded = workflow.load_state("reviews.json"), workflow.load_state("uploaded.json")
    if not names:
        print("出力シート（ヒトマネ出力_…）がありません。GAS の③で原稿を作ってください")
    for n in names:
        rv = reviews.get(n, {})
        ups = [f"{v.get('company') or k.split('|')[0]} {v['uploaded_at']}" for k, v in uploaded.items()
               if k == n or k.endswith("|" + n)]
        print(f"{n}  チェック:{rv.get('status', '未実施')}  入稿:{'、'.join(ups) or '未'}")
    return 0


def _manuscript(args, settings):
    return workflow.load_manuscript(settings, sheet=args.sheet, csv=args.csv)


def cmd_check(args) -> int:
    settings, rules = _settings(args), config.load("rules.json")
    ms = _manuscript(args, settings)
    res = workflow.check(ms, rules)
    for i in res["sheet_issues"]:
        print(f"シート全体: {'エラー' if i['severity'] == 'error' else '注意'} {i['column']}：{i['message']}")
    if res["rows"] <= 30:
        for n, issues in enumerate(res["issues"], start=2):
            errs = sum(1 for i in issues if i["severity"] == "error")
            print(f"{n}行目: {'NG' if errs else ('要確認' if issues else 'OK')}（{len(issues)}件）")
    else:
        print("、".join(f"{k} {v}件" for k, v in res["counts"].items()))
    print(f"\n{ms.name}：原稿 {res['rows']}件、判定 {res['status']}")
    print(f"レポート: {res['report']}")
    return 0 if res["status"] != "NG" else 2


def cmd_upload(args) -> int:
    from .uploader import HitomaneUploader

    settings, rules = _settings(args), config.load("rules.json")
    ms = _manuscript(args, settings)
    info = _info(args, settings)
    key = accounts.account_key(info)
    stop = workflow.upload_problem(ms, key)
    if stop:
        print(f"入稿しません: {stop}")
        return 1
    rv = workflow.load_state("reviews.json")[ms.name]
    paths = workflow.write_csvs(ms, settings, rules)
    print(f"入れる会社: {accounts.label(info)}\nシート: {ms.name}\n原稿数: {len(ms.rows)}\nチェック結果: {rv['status']}（{rv['checked_at']}）")
    print("CSV: " + "、".join(str(p) for p in paths))
    if rv["status"] == "要確認":
        print("※ 注意の指摘があります。レポートを確かめてから入稿してください")
    if args.dry_run:
        print("--dry-run のため、ここで止めます（取り込みはしていません）")
        return 0
    up = HitomaneUploader(info, settings["hitomane"], config.OUTPUT_DIR / ms.name, headed=args.headed)
    acct = up.account()
    workflow.save_total(key, acct["total"], info.get("company", ""))
    stop = workflow.branch_problem(ms, acct["branches"], info.get("company", ""))
    if stop:
        print(f"入稿しません: {stop}")
        return 1
    print(workflow.total_note(acct["total"], len(ms.rows), rules))
    if not args.yes and input(f"{accounts.label(info)} に取り込みますか？ [y/N] > ").strip().lower() != "y":
        print("中止しました")
        return 1
    results = up.upload(paths)
    workflow.record_upload(ms, results, key, info.get("company", ""))
    ok = bool(results) and all(r.ok for r in results) and len(results) == len(paths)
    for r in results:
        print(f"{'成功' if r.ok else '失敗'}: {r.file} {r.message}\n  {r.row_text}\n  画面: {r.screenshot}")
    if len(results) < len(paths):
        print(f"失敗したため、残りの {len(paths) - len(results)} ファイルは取り込んでいません")
    return 0 if ok else 2


def cmd_login(args) -> int:
    """ログインできるかを確かめ、募集管理の全件数と拠点を読む（全件数は覚えておく。ヒトマネは変えない）。"""
    from .uploader import HitomaneUploader

    settings, rules = _settings(args), config.load("rules.json")
    try:
        names = [c["code"] for c in accounts.companies(settings)] if args.all else [args.company]
        infos = [accounts.login_info(settings, company=n) for n in names]
    except Exception as e:
        print(f"ログイン情報を読めませんでした: {e}")
        return 1
    failed = 0
    for info in infos:
        print(f"\n{accounts.label(info)} に {info['login_id']} でログインします（{info['url']}）")
        try:
            acct = HitomaneUploader(info, settings["hitomane"], config.OUTPUT_DIR / "ログイン確認",
                                    headed=args.headed).account()
        except Exception as e:
            print(f"ログインできませんでした: {e}")
            failed += 1
            continue
        total = acct["total"]
        workflow.save_total(accounts.account_key(info), total, info.get("company", ""))
        print("ログインできました")
        if total is None:
            print("募集管理の全件数は読めませんでした")
        else:
            print(f"募集管理の全件数: {total:,}件（上限 {rules['total_limit']:,}件、あと {rules['total_limit'] - total:,}件）")
        print("拠点: " + ("、".join(f"{b['name']}（{b['code']}）" for b in acct["branches"]) or "読めませんでした"))
    if len(infos) > 1:
        print(f"\n{len(infos)}社中 {len(infos) - failed}社にログインできました")
    return 2 if failed else 0


def cmd_takedown(args) -> int:
    """掲載開始日の期間の掲載中の原稿を、開始日・終了日を2年前・非掲載にして取り込み直す。"""
    from datetime import date

    from . import takedown
    from .csv_export import read_csv
    from .exporter import HitomaneExporter
    from .uploader import HitomaneUploader

    settings, rules = _settings(args), config.load("rules.json")
    try:
        cond = takedown.Conditions(takedown.parse_day(args.date_from), takedown.parse_day(args.date_to))
    except ValueError as e:
        print(e)
        return 1
    if cond.start_from > cond.start_to:
        print("期間の「から」が「まで」より後です")
        return 1
    info = _info(args, settings)
    key = accounts.account_key(info)
    today = date.today()
    prepared = None if args.prepare_only else takedown.find_prepared(key, cond, today)
    print(f"会社: {accounts.label(info)}\nログインID: {info['login_id']}\n条件: {cond.describe()}")
    if prepared:
        print(f"今日の「確認だけ」（{prepared['prepared_at']}）のファイルを使います（取り出しは省きます）")
    else:
        out = config.OUTPUT_DIR / f"取り下げ_{key}_{today:%Y%m%d}_{cond.label()}"
        res = HitomaneExporter(info, settings["hitomane"], out, headed=args.headed).export(cond, out / "取り出し.csv")
        if not res["file"]:
            print("条件に合う原稿はありません。取り下げるものはありません")
            return 0
        exported = read_csv(Path(res["file"]).read_bytes(), "取り出し")
        try:
            branch = takedown.pick_branch(exported, res["branches"])
        except RuntimeError as e:
            print(e)
            return 1
        rw = takedown.rewrite(exported, cond, branch, today)
        files = []
        from .csv_export import split_rows, to_csv_bytes
        for n, part in enumerate(split_rows(rw.manuscript, rules["max_rows_per_file"]), start=1):
            f = out / f"取り下げ_{n}.csv"
            f.write_bytes(to_csv_bytes(part, **settings["csv"]))
            files.append(str(f))
        prepared = {"searched": res["count"], "rows": len(rw.manuscript.rows), "skipped": rw.skipped,
                    "new_date": rw.new_date, "branch": branch, "files": files if rw.manuscript.rows else []}
        takedown.save_prepared(key, cond, {**prepared, "company": info.get("company", "")}, today)
    b = prepared["branch"]
    print(f"拠点: {b['name']}（{b['code']}）\n検索の件数: {prepared['searched']}件\n取り下げる原稿: {prepared['rows']}件")
    for reason, n in prepared["skipped"].items():
        print(f"  除いた原稿（{reason}）: {n}件")
    print(f"書き換え: 開始日・終了日 → {prepared['new_date']}、ステータス → 非掲載")
    print("ファイル: " + "、".join(prepared["files"]))
    if args.prepare_only:
        print("確認だけのため、取り込んでいません。取り下げるときは --prepare-only を付けずに実行してください（今日のうちならこのファイルを使います）")
        return 0
    if not prepared["rows"]:
        print("取り下げる原稿がありません")
        return 0
    if not args.yes and input(f"{accounts.label(info)} の {prepared['rows']}件を取り下げますか？ [y/N] > ").strip().lower() != "y":
        print("中止しました")
        return 1
    out_dir = Path(prepared["files"][0]).parent
    results = HitomaneUploader(info, settings["hitomane"], out_dir, headed=args.headed).upload(
        [Path(f) for f in prepared["files"]])
    ok = len(results) == len(prepared["files"]) and all(r.ok for r in results)
    takedown.record({"account": key, "company": info.get("company", ""), "login_id": info["login_id"],
                     "conditions": cond.describe(), "rows": prepared["rows"], "ok": ok,
                     "results": [{"file": r.file, "ok": r.ok, "message": r.message, "row": r.row_text} for r in results]})
    for r in results:
        print(f"{'成功' if r.ok else '失敗'}: {r.file} {r.message}\n  {r.row_text}")
    if len(results) < len(prepared["files"]):
        print(f"失敗したため、残りの {len(prepared['files']) - len(results)} ファイルは取り込んでいません")
    print("取り下げました" if ok else "取り下げは途中で止まりました。取込ファイル一覧を確かめてください")
    return 0 if ok else 2


COMPANY_HELP = "入れる会社（会社名・会社のコード・会社名の一部）。1社だけのときと settings の company があるときは省ける"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hitomane_agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("survey", help="ヒトマネ管理画面の作りを調べて output に保存する（取り込み・取り下げはしない）")
    s.add_argument("--headed", action="store_true", help="ブラウザを表示して動かす")
    s.add_argument("--sample", nargs="?", const="auto",
                   help="この募集番号の原稿を1件だけ取り出して、CSV の見本を保存する（番号を省くと、一覧のいちばん上の原稿を使う）")
    s.add_argument("--user", help="使うログインID（またはログイン情報シートのメモの名前）。省略時は settings の login_user")
    s.add_argument("--company", help=COMPANY_HELP)
    s.set_defaults(func=cmd_survey)

    s = sub.add_parser("companies", help="会社の一覧（ログイン情報シートの会社の行）")
    s.set_defaults(func=cmd_companies)

    s = sub.add_parser("list", help="出力シートの一覧とチェック・入稿の状態")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("login", help="ログインできるかを確かめ、募集管理の全件数と拠点を読む（ヒトマネは変えない）")
    s.add_argument("--headed", action="store_true", help="ブラウザを表示して動かす")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--company", help=COMPANY_HELP)
    g.add_argument("--all", action="store_true", help="ログイン情報シートの全社を順に確かめる")
    s.add_argument("--user", help="使うログインID（省略時は settings の login_user）")
    s.set_defaults(func=cmd_login)

    for name, func, text in (("check", cmd_check, "入稿前のチェック"), ("upload", cmd_upload, "ヒトマネに取り込む")):
        s = sub.add_parser(name, help=text)
        g = s.add_mutually_exclusive_group(required=True)
        g.add_argument("--sheet", help="出力シートの名前（ヒトマネ出力_…）")
        g.add_argument("--csv", help="シートの代わりに読む CSV（取り出した CSV をそのまま取り込み直すときなど）")
        s.add_argument("--user", help="使うログインID（省略時は settings の login_user）")
        if name == "upload":
            s.add_argument("--company", help=COMPANY_HELP)
            s.add_argument("--yes", action="store_true", help="確認を聞かずに取り込む")
            s.add_argument("--dry-run", action="store_true", help="CSV を作るところまで（取り込まない）")
            s.add_argument("--headed", action="store_true", help="ブラウザを表示して動かす")
        s.set_defaults(func=func)

    s = sub.add_parser("takedown", help="掲載開始日の期間の掲載中の原稿を取り下げる（開始日・終了日を2年前・非掲載にして取り込み直す）")
    s.add_argument("--from", dest="date_from", required=True, help="掲載開始日の期間の初め（2026/10/01 の形）")
    s.add_argument("--to", dest="date_to", required=True, help="掲載開始日の期間の終わり（2026/10/31 の形）")
    s.add_argument("--prepare-only", action="store_true", help="確認だけ：取り出して件数を見る（取り込まない）")
    s.add_argument("--yes", action="store_true", help="確認を聞かずに取り下げる")
    s.add_argument("--headed", action="store_true", help="ブラウザを表示して動かす")
    s.add_argument("--user", help="使うログインID（省略時は settings の login_user）")
    s.add_argument("--company", help=COMPANY_HELP)
    s.set_defaults(func=cmd_takedown)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
