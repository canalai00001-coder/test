"""ヒトマネ入稿ツールのコマンド。

  python -m hitomane_agent survey [--headed] [--sample [募集番号]]   管理画面の画面調査
"""
import argparse
import sys
from datetime import datetime

from . import accounts, config


def cmd_survey(args) -> int:
    from .survey import run_survey

    settings = config.load("settings.json")
    if args.user:
        settings["login_user"] = args.user
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hitomane_agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("survey", help="ヒトマネ管理画面の作りを調べて output に保存する（取り込み・取り下げはしない）")
    s.add_argument("--headed", action="store_true", help="ブラウザを表示して動かす")
    s.add_argument("--sample", nargs="?", const="auto",
                   help="この募集番号の原稿を1件だけ取り出して、CSV の見本を保存する（番号を省くと、一覧のいちばん上の原稿を使う）")
    s.add_argument("--user", help="使うログインID（またはログイン情報シートのメモの名前）。省略時は settings の login_user")
    s.set_defaults(func=cmd_survey)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
