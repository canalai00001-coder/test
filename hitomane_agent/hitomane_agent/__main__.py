"""ヒトマネ入稿ツールのコマンド。

  python -m hitomane_agent survey [--headed] [--sample [募集番号]]       管理画面の画面調査
  python -m hitomane_agent list                                         出力シートの一覧とチェックの状態
  python -m hitomane_agent check (--sheet 名前 | --csv パス)            入稿前のチェック
  python -m hitomane_agent upload (--sheet 名前 | --csv パス) [--yes] [--dry-run]   ヒトマネに取り込む
"""
import argparse
import sys
from datetime import datetime

from . import accounts, config, workflow


def _settings(args) -> dict:
    settings = config.load("settings.json")
    if getattr(args, "user", None):
        settings["login_user"] = args.user
    return settings


def cmd_survey(args) -> int:
    from .survey import run_survey

    settings = _settings(args)
    try:
        info = accounts.login_info(settings)
    except Exception as e:
        print(f"ログイン情報を読めませんでした: {e}")
        return 1
    out = config.OUTPUT_DIR / f"画面調査_{datetime.now():%Y%m%d_%H%M}"
    h = settings["hitomane"]
    print(f"ヒトマネ管理画面を {info['login_id']} で調べます（{info['url']}）。取り込み・取り下げはしません")
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
        rv, up = reviews.get(n, {}), uploaded.get(n)
        print(f"{n}  チェック:{rv.get('status', '未実施')}  入稿:{up['uploaded_at'] if up else '未'}")
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
    stop = workflow.upload_problem(ms)
    if stop:
        print(f"入稿しません: {stop}")
        return 1
    rv = workflow.load_state("reviews.json")[ms.name]
    paths = workflow.write_csvs(ms, settings, rules)
    print(f"シート: {ms.name}\n原稿数: {len(ms.rows)}\nチェック結果: {rv['status']}（{rv['checked_at']}）")
    print("CSV: " + "、".join(str(p) for p in paths))
    if rv["status"] == "要確認":
        print("※ 注意の指摘があります。レポートを確かめてから入稿してください")
    if args.dry_run:
        print("--dry-run のため、ここで止めます（取り込みはしていません）")
        return 0
    info = accounts.login_info(settings)
    up = HitomaneUploader(info, settings["hitomane"], config.OUTPUT_DIR / ms.name, headed=args.headed)
    print(workflow.total_note(up.total(), len(ms.rows), rules))
    if not args.yes and input(f"ヒトマネ（{info['login_id']}）に取り込みますか？ [y/N] > ").strip().lower() != "y":
        print("中止しました")
        return 1
    results = up.upload(paths)
    workflow.record_upload(ms, results)
    ok = bool(results) and all(r.ok for r in results) and len(results) == len(paths)
    for r in results:
        print(f"{'成功' if r.ok else '失敗'}: {r.file} {r.message}\n  {r.row_text}\n  画面: {r.screenshot}")
    if len(results) < len(paths):
        print(f"失敗したため、残りの {len(paths) - len(results)} ファイルは取り込んでいません")
    return 0 if ok else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hitomane_agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("survey", help="ヒトマネ管理画面の作りを調べて output に保存する（取り込み・取り下げはしない）")
    s.add_argument("--headed", action="store_true", help="ブラウザを表示して動かす")
    s.add_argument("--sample", nargs="?", const="auto",
                   help="この募集番号の原稿を1件だけ取り出して、CSV の見本を保存する（番号を省くと、一覧のいちばん上の原稿を使う）")
    s.add_argument("--user", help="使うログインID（またはログイン情報シートのメモの名前）。省略時は settings の login_user")
    s.set_defaults(func=cmd_survey)

    s = sub.add_parser("list", help="出力シートの一覧とチェック・入稿の状態")
    s.set_defaults(func=cmd_list)

    for name, func, text in (("check", cmd_check, "入稿前のチェック"), ("upload", cmd_upload, "ヒトマネに取り込む")):
        s = sub.add_parser(name, help=text)
        g = s.add_mutually_exclusive_group(required=True)
        g.add_argument("--sheet", help="出力シートの名前（ヒトマネ出力_…）")
        g.add_argument("--csv", help="シートの代わりに読む CSV（取り出した CSV をそのまま取り込み直すときなど）")
        s.add_argument("--user", help="使うログインID（省略時は settings の login_user）")
        if name == "upload":
            s.add_argument("--yes", action="store_true", help="確認を聞かずに取り込む")
            s.add_argument("--dry-run", action="store_true", help="CSV を作るところまで（取り込まない）")
            s.add_argument("--headed", action="store_true", help="ブラウザを表示して動かす")
        s.set_defaults(func=func)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
