"""使い方:
    python -m qmate_agent list                         # 出力シートの一覧と検品シートの判定
    python -m qmate_agent check --sheet 出力_G1_...      # チェック → output/ にレポートと CSV
    python -m qmate_agent upload --sheet 出力_G1_... --dry-run   # 入稿前の最終確認だけ
    python -m qmate_agent upload --sheet 出力_G1_...      # Q-mate に CSV を入稿
    python -m qmate_agent schedule                     # 入稿予定表の今日の行を生成 → チェック → 入稿
"""
import argparse
import json
import os
import sys
from datetime import date, datetime
from types import SimpleNamespace

from . import config
from .checks import Issue, check_sheet, status_of
from .csv_export import to_csv_bytes
from .report import render


def _state(name: str) -> dict:
    path = config.STATE_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save_state(name: str, data: dict) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (config.STATE_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _spreadsheet(settings):
    from .sheet import Spreadsheet
    return Spreadsheet(settings)


def inspection_issue(name: str, verdicts: dict, settings: dict) -> list[Issue]:
    v = verdicts.get(name)
    if v is None:
        return [Issue("warning", "検品シート", "検品シートにこのシートの判定がありません。GAS の検品を実行してください")]
    if v != settings["inspection_ok_value"]:
        return [Issue("error", "検品シート", f"検品シートの判定が「{v}」です")]
    return []


def cmd_list(args) -> int:
    settings = config.load("settings.json")
    book = _spreadsheet(settings)
    verdicts = book.inspection_verdicts()
    reviews = _state("reviews.json")
    names = book.output_sheet_names()
    if not names:
        print("出力シートがありません。GAS で原稿を生成してください")
    for n in names:
        rv = reviews.get(n, {})
        print(f"{n}  検品:{verdicts.get(n, '未実施')}  AIチェック:{rv.get('status', '未実施')}")
    return 0


def cmd_check(args) -> int:
    settings, rules = config.load("settings.json"), config.load("rules.json")
    if args.csv:
        from .sheet import manuscript_from_csv
        ms, verdicts, book = manuscript_from_csv(args.csv), {}, None
    else:
        book = _spreadsheet(settings)
        ms, verdicts = book.manuscript(args.sheet), book.inspection_verdicts()
    for col in ms.fill_blanks(rules.get("blank_defaults", {})):
        print(f"{col} が空欄の原稿に「{rules['blank_defaults'][col]}」を入れました")

    sheet_issues = [] if args.csv else inspection_issue(ms.name, verdicts, settings)
    results = check_sheet(ms, rules)
    summaries = [""] * len(ms.rows)
    if not args.no_ai:
        from .ai_review import AIReviewer
        reviewer = AIReviewer()
        for i, row in enumerate(ms.rows):
            try:
                ai_issues, summaries[i] = reviewer.review(row, results[i])
                results[i] += ai_issues
            except Exception as e:
                results[i].append(Issue("error", "全体", f"AIチェックに失敗しました: {e}", "ai"))
            print(f"  AIチェック {i + 1}/{len(ms.rows)}", end="\r")

    overall = status_of(sheet_issues + [x for r in results for x in r])
    out_dir = config.OUTPUT_DIR / ms.name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.html").write_text(render(ms.name, ms.rows, sheet_issues, results, summaries), encoding="utf-8")
    (out_dir / f"{ms.name}.csv").write_bytes(to_csv_bytes(ms, **settings["csv"]))

    reviews = _state("reviews.json")
    reviews[ms.name] = {"hash": ms.data_hash(), "status": overall, "ai": not args.no_ai,
                        "rows": len(ms.rows), "checked_at": datetime.now().isoformat(timespec="seconds")}
    _save_state("reviews.json", reviews)

    if book is not None:
        table = [["シート", "行", "判定", "種類", "列", "内容", "修正案", "判定元", "チェック日時"]]
        now = f"{datetime.now():%Y/%m/%d %H:%M}"
        for i in sheet_issues:
            table.append([ms.name, "", "", i.severity, i.column, i.message, i.suggestion, i.source, now])
        for n, issues in enumerate(results, start=2):
            for i in issues:
                table.append([ms.name, str(n), status_of(issues), i.severity, i.column, i.message,
                              i.suggestion, "AI" if i.source == "ai" else "ルール", now])
        book.write_results(table)

    if len(results) <= 30:
        for n, issues in enumerate(results, start=2):
            print(f"{n}行目: {status_of(issues)}（{len(issues)}件）")
    else:
        counts = {}
        for issues in results:
            counts[status_of(issues)] = counts.get(status_of(issues), 0) + 1
        print("、".join(f"{k} {v}件" for k, v in counts.items()))
    print(f"\n判定: {overall}")
    print(f"レポート: {out_dir / 'report.html'}")
    print(f"CSV: {out_dir / (ms.name + '.csv')}")
    return 0 if overall != "NG" else 2


def cmd_upload(args) -> int:
    settings, rules = config.load("settings.json"), config.load("rules.json")
    book = _spreadsheet(settings)
    ms = book.manuscript(args.sheet)
    ms.fill_blanks(rules.get("blank_defaults", {}))
    rv = _state("reviews.json").get(ms.name)
    uploaded = _state("uploaded.json")

    stop = None
    if not rv:
        stop = "check をしていません"
    elif rv["hash"] != ms.data_hash():
        stop = "check のあとにシートの内容が変わっています。check をやり直してください"
    elif settings.get("require_ai_check", True) and not rv.get("ai"):
        stop = "AIチェックなしの結果です。--no-ai を付けずに check してください"
    elif rv["status"] == "NG":
        stop = "チェック結果が NG です。シートを直して check をやり直してください"
    elif uploaded.get(ms.name, {}).get("hash") == rv["hash"]:
        stop = f"同じ内容を {uploaded[ms.name]['uploaded_at']} に入稿済みです"
    else:
        insp = inspection_issue(ms.name, book.inspection_verdicts(), settings)
        if any(i.severity == "error" for i in insp):
            stop = insp[0].message
    if stop:
        print(f"入稿しません: {stop}")
        return 1

    csv_path = config.OUTPUT_DIR / ms.name / f"{ms.name}.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_bytes(to_csv_bytes(ms, **settings["csv"]))
    print(f"シート: {ms.name}\n原稿数: {len(ms.rows)}\nチェック結果: {rv['status']}（{rv['checked_at']}）\nCSV: {csv_path}")
    if rv["status"] == "要確認":
        print("※ 注意の指摘があります。レポートを確認済みであることを確かめてください")
    if args.dry_run:
        print("--dry-run のため、ここで止めます")
        return 0
    if not args.yes and input("Q-mate に入稿しますか？ [y/N] > ").strip().lower() != "y":
        print("中止しました")
        return 1

    from .uploader import QmateUploader
    result = QmateUploader(settings["qmate"], headless=not args.headed,
                           out_dir=config.OUTPUT_DIR / ms.name).upload(csv_path, ms.name)
    print(("成功: " if result.ok else "失敗: ") + result.message)
    print(f"結果画面: {result.screenshot}")
    if result.ok:
        uploaded[ms.name] = {"hash": rv["hash"], "rows": len(ms.rows),
                             "uploaded_at": datetime.now().isoformat(timespec="seconds")}
        _save_state("uploaded.json", uploaded)
    return 0 if result.ok else 2


def cmd_schedule(args) -> int:
    from . import schedule as sc

    settings, rules = config.load("settings.json"), config.load("rules.json")
    today = date.fromisoformat(args.date) if args.date else date.today()
    book = _spreadsheet(settings)
    plans = sc.read_plan(book.plan_table(), today)
    if args.row:
        targets = [p for p in plans if p.row == args.row]
    else:
        targets = [p for p in plans if p.run_date == today]
    done = _state("schedule.json")
    if not args.force:
        skipped = [p for p in targets if p.key in done]
        for p in skipped:
            print(f"入稿予定表 {p.row}行目は {done[p.key]['finished_at']} に実行済みです（やり直すときは --force）")
        targets = [p for p in targets if p.key not in done]
    if not targets:
        print(f"入稿予定表に、{today:%Y/%m/%d} に実行する行がありません")
        return 0

    company = settings["qmate"].get("company")
    defaults = settings["schedule_defaults"]
    print(f"入稿予定表から {len(targets)}件 を実行します")
    for p in targets:
        status = args.status or defaults.get("ステータス")
        print(f"  {p.row}行目: {p.company} / {p.category} / {'夜勤あり' if p.night else '夜勤なし'} / "
              f"{args.count or p.count}件 / ステータス {status}")
        if company and p.company != company:
            print(f"入稿先に設定している会社（{company}）と違うため実行できません。settings.json の qmate を確認してください")
            return 1
    if not args.yes and input("原稿を生成して Q-mate に入稿します。よろしいですか？ [y/N] > ").strip().lower() != "y":
        print("中止しました")
        return 1

    url, token = settings.get("gas_webapp_url", ""), os.environ.get("QMATE_GAS_TOKEN", "")
    if not url.startswith("https://") or not token:
        print("GAS のウェブアプリの URL（settings.json の gas_webapp_url）と、環境変数 QMATE_GAS_TOKEN を設定してください")
        return 1
    gas = sc.GasRunner(url, token)
    run_id = datetime.now().strftime("%H%M")
    failed = 0
    for p in targets:
        print(f"\n=== 入稿予定表 {p.row}行目 ===")
        try:
            values = sc.config_row(p, defaults, rules, today, run_id, args.status, args.count)
            config_row = book.append_config_row(values)
            print(f"実行設定 {config_row}行目に予約しました。GAS で生成します")
            gas.run()
            text = sc.wait_generated(book, config_row, settings.get("generate_timeout_min", 30) * 60, 15, print)
            sheets = sc.output_sheets(text)
            if text.startswith("❌") or not sheets:
                raise RuntimeError(f"生成に失敗しました: {text}")
            print(f"生成しました: {', '.join(sheets)}")
            for name in sheets:
                print(f"\n--- チェック: {name} ---")
                if cmd_check(SimpleNamespace(sheet=name, csv=None, no_ai=not settings.get("require_ai_check"))) == 2:
                    raise RuntimeError(f"{name} のチェック結果が NG のため入稿しません。レポートを確認してください")
                print(f"\n--- 入稿: {name} ---")
                if cmd_upload(SimpleNamespace(sheet=name, dry_run=args.dry_run, headed=args.headed, yes=True)) != 0:
                    raise RuntimeError(f"{name} の入稿に失敗しました")
            result = f"{'CSV作成まで' if args.dry_run else '入稿済み'}（{datetime.now():%m/%d %H:%M}）{', '.join(sheets)}"
            if not args.dry_run:
                done[p.key] = {"sheets": sheets, "finished_at": datetime.now().isoformat(timespec="seconds")}
                _save_state("schedule.json", done)
        except Exception as e:
            failed += 1
            result = f"失敗（{datetime.now():%m/%d %H:%M}）{e}"
            print(result)
        book.write_plan_result(p.row, result)
    print(f"\n完了: {len(targets) - failed}件 成功 / {failed}件 失敗")
    return 0 if not failed else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qmate_agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="出力シートの一覧").set_defaults(func=cmd_list)

    c = sub.add_parser("check", help="出力シートをチェックしてレポートと CSV を作る")
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--sheet", help="出力シート名")
    g.add_argument("--csv", help="出力シートを書き出した CSV（テスト用）")
    c.add_argument("--no-ai", action="store_true", help="ルールチェックだけにする")
    c.set_defaults(func=cmd_check)

    u = sub.add_parser("upload", help="チェック済みの出力シートを Q-mate に入稿する")
    u.add_argument("--sheet", required=True, help="出力シート名")
    u.add_argument("--dry-run", action="store_true", help="入稿前の確認と CSV 作成まで")
    u.add_argument("--headed", action="store_true", help="ブラウザを表示して動かす")
    u.add_argument("--yes", action="store_true", help="実行前の確認を省く")
    u.set_defaults(func=cmd_upload)

    s = sub.add_parser("schedule", help="入稿予定表の行を生成からチェック、入稿まで行う")
    s.add_argument("--date", help="この日付の行を実行する（YYYY-MM-DD。省略時は今日）")
    s.add_argument("--row", type=int, help="入稿予定表のこの行だけを、実行日に関係なく実行する")
    s.add_argument("--status", help="ステータスを上書きする（試すときは 下書き）")
    s.add_argument("--count", type=int, help="原稿数を上書きする（試すときに少なくする）")
    s.add_argument("--dry-run", action="store_true", help="生成とチェック、CSV 作成までで止める")
    s.add_argument("--headed", action="store_true", help="入稿のブラウザを表示する")
    s.add_argument("--force", action="store_true", help="実行済みの行ももう一度実行する")
    s.add_argument("--yes", action="store_true", help="実行前の確認を省く（毎日の自動実行用）")
    s.set_defaults(func=cmd_schedule)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
