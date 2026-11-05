"""使い方:
    python -m qmate_agent list                         # 出力シートの一覧と検品シートの判定
    python -m qmate_agent check --sheet 出力_G1_...      # チェック → output/ にレポートと CSV
    python -m qmate_agent upload --sheet 出力_G1_... --dry-run   # 入稿前の最終確認だけ
    python -m qmate_agent upload --sheet 出力_G1_...      # Q-mate に CSV を入稿
    python -m qmate_agent schedule                     # 入稿予定表の今日の行を生成 → チェック → 取り下げ → 入稿
    python -m qmate_agent takedown --company AspiRove株式会社   # 今の「公開」の原稿を Q-mate から取り下げる
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


def _settings(args) -> dict:
    """settings.json。入寮用など別のスプレッドシートの出力シートを扱うときは、その ID に差し替える。"""
    settings = config.load("settings.json")
    if getattr(args, "spreadsheet_id", None):
        settings = dict(settings, spreadsheet_id=args.spreadsheet_id)
    return settings


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
    settings, rules = _settings(args), config.load("rules.json")
    local = getattr(args, "manuscript", None)  # ツールで生成した原稿（シートを経由しない）
    if args.csv:
        from .sheet import manuscript_from_csv
        ms, verdicts, book = manuscript_from_csv(args.csv), {}, None
    elif local is not None:
        book = _spreadsheet(settings)
        ms, verdicts = local, {}
    else:
        book = _spreadsheet(settings)
        ms, verdicts = book.manuscript(args.sheet), book.inspection_verdicts()
    for col in ms.fill_blanks(rules.get("blank_defaults", {})):
        print(f"{col} が空欄の原稿に「{rules['blank_defaults'][col]}」を入れました")

    # GAS の検品は、GAS で作った出力シートだけが対象（ツールで生成した原稿は、このチェックで同じ項目を見る）
    sheet_issues = [] if args.csv or local is not None else inspection_issue(ms.name, verdicts, settings)
    results = check_sheet(ms, rules, one_segment=getattr(args, "one_segment", False))
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
    settings, rules = _settings(args), config.load("rules.json")
    book = _spreadsheet(settings)
    local = getattr(args, "manuscript", None)
    ms = local if local is not None else book.manuscript(args.sheet)
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
        insp = [] if local is not None else inspection_issue(ms.name, book.inspection_verdicts(), settings)
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

    from .accounts import qmate_config
    from .uploader import QmateUploader
    company = getattr(args, "company", None) or settings["qmate"].get("company")
    print(f"入稿先: {company}")
    result = QmateUploader(qmate_config(settings, company), headless=not args.headed,
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
    # 取り下げ予定表（入稿はせず、取り下げだけをする行）。--row で入稿予定表の行を指定したときは動かさない
    td_sheet = settings.get("takedown_sheet", "取り下げ予定表")
    td_rows = sc.read_takedown_plan(book.plan_table(td_sheet), today)
    if args.takedown_row:
        td_targets = [r for r in td_rows if r.row == args.takedown_row]
    elif args.row:
        td_targets = []
    else:
        td_targets = [r for r in td_rows if r.run_date == today]
    if not args.force:
        for r in [r for r in td_targets if r.key in done]:
            print(f"取り下げ予定表 {r.row}行目は {done[r.key]['finished_at']} に実行済みです（やり直すときは --force）")
        td_targets = [r for r in td_targets if r.key not in done]
    if not targets and not td_targets:
        print(f"入稿予定表・取り下げ予定表に、{today:%Y/%m/%d} に実行する行がありません")
        return 0

    from . import accounts
    gas_targets = settings["schedule_targets"]
    commutes = {}
    from .takedown import describe
    for r in td_targets:
        print(f"取り下げ予定表 {r.row}行目: {r.company} / {describe(r.date_from, r.date_to)}"
              f"{f' / メモに「{r.memo}」を含む' if r.memo else ''} / 対象ステータス "
              f"{r.status or settings['takedown']['export_status']} → 取り下げ（{settings['takedown']['update_type']}）")
        problem = accounts.login_problem(settings, r.company)
        if problem:
            print(problem)
            return 1
    if targets:
        print(f"入稿予定表から {len(targets)}件 を実行します")
    for p in targets:
        try:
            commutes[p.row] = sc.commute_of(p, settings.get("schedule_default_commute", "通勤"))
        except ValueError as e:
            print(f"  {p.row}行目: {e}")
            return 1
        t = gas_targets[commutes[p.row]]
        defaults = t.get("defaults", {})
        print(f"  {p.row}行目: {p.company} / {p.category} / {'夜勤あり' if p.night else '夜勤なし'} / "
              f"{commutes[p.row]}（{'ツール' if t.get('engine') == 'python' else commutes[p.row] + '用の GAS'}で生成） / {p.employment or defaults.get('雇用形態')} / "
              f"{args.count or p.count}件 / ステータス {args.status or p.status or defaults.get('ステータス')}")
        problem = "" if args.dry_run else accounts.login_problem(settings, p.company)
        if problem:
            print(problem)
            return 1

    runners = {}
    for c in sorted(set(commutes.values())):
        t = gas_targets[c]
        if t.get("engine") == "python":
            continue  # ツールで生成するので GAS は使わない
        url, token = t.get("gas_webapp_url", "").strip(), os.environ.get(t["token_env"], "").strip()
        missing = []
        if not url.startswith("https://"):
            missing.append(f"・{c}用の GAS のウェブアプリの URL が settings.json に入っていません"
                           f"（schedule_targets の「{c}」の gas_webapp_url。今の値: {url or '空欄'}）")
        if not token:
            missing.append(f"・{c}用の合言葉が登録されていません（setx {t['token_env']} 合言葉 で登録し、"
                           "コマンドプロンプトを開き直してください）")
        if missing:
            print("\n".join(missing))
            return 1
        runners[c] = sc.GasRunner(url, token)
    # 前回分の取り下げは、会社ごとに1回だけ、その会社の最初の入稿の前に行う。
    # 下書きだけの行（試運転）しかない会社では行わない（本番の公開原稿を消さないため）
    td = settings.get("takedown", {})
    takedown_companies = set()
    if td.get("enabled") and not args.no_takedown:
        for p in targets:
            st = args.status or p.status or gas_targets[commutes[p.row]].get("defaults", {}).get("ステータス")
            if st == "公開":
                takedown_companies.add(p.company)
    # 取り下げ予定表に今日の行がある会社は、その行の指定（期間など）で取り下げるので、入稿前の取り下げはしない
    takedown_companies -= {r.company for r in td_targets}
    if takedown_companies:
        print(f"※ {'、'.join(sorted(takedown_companies))} は、入稿の前に Q-mate にある"
              f"「{td['export_status']}」の原稿をすべて取り下げます（{td['update_type']}）")
    question = "原稿を生成して Q-mate に入稿します" if targets else "Q-mate の原稿を取り下げます（元には戻せません）"
    if not args.yes and input(f"{question}。よろしいですか？ [y/N] > ").strip().lower() != "y":
        print("中止しました")
        return 1

    run_id = datetime.now().strftime("%H%M")
    failed = 0
    takedown_done = {}
    for r in td_targets:
        print(f"\n=== 取り下げ予定表 {r.row}行目 ===")
        res = _takedown(r.company, settings, args.headed, args.dry_run, date_from=r.date_from, date_to=r.date_to,
                        memo=r.memo, export_status=r.status or None)
        if isinstance(res, Exception):
            failed += 1
            text = f"失敗（{datetime.now():%m/%d %H:%M}）{res}"
        else:
            text = (f"{'取り出しと分割まで' if args.dry_run else '取り下げ済み'}（{datetime.now():%m/%d %H:%M}）"
                    f"{res['count']}件 / {res['span']}")
            if not args.dry_run:
                done[r.key] = {"count": res["count"], "finished_at": datetime.now().isoformat(timespec="seconds")}
                _save_state("schedule.json", done)
        print(text)
        book.write_plan_result(r.row, text, sheet=td_sheet)
    for p in targets:
        c = commutes[p.row]
        t = gas_targets[c]
        gen_book = _spreadsheet(dict(settings, spreadsheet_id=t["spreadsheet_id"]))
        print(f"\n=== 入稿予定表 {p.row}行目（{c}） ===")
        try:
            if t.get("engine") == "python":
                manuscripts = [_generate_locally(p, c, t, settings, rules, today, run_id, args)]
                sheets = [m.name for m in manuscripts]
                _check_and_upload(manuscripts, p, t, settings, args, takedown_companies, takedown_done)
                result = f"{'CSV作成まで' if args.dry_run else '入稿済み'}（{datetime.now():%m/%d %H:%M}）{', '.join(sheets)}"
                if not args.dry_run:
                    done[p.key] = {"sheets": sheets, "finished_at": datetime.now().isoformat(timespec="seconds")}
                    _save_state("schedule.json", done)
                book.write_plan_result(p.row, result)
                continue
            values = sc.config_row(p, c, t, rules, today, run_id, args.status, args.count)
            # GAS は実行状況が空欄の行をすべて生成するので、ほかの未実行の予約行があると一緒に作られてしまう
            others = gen_book.pending_config_rows(sc.status_column(c))
            if others:
                raise RuntimeError(f"{c}用スプレッドシートの実行設定に、未実行の予約行（{sc.row_ranges(others)}行目）があります。"
                                   "このまま生成すると一緒に作られてしまうため止めました。その行を実行するか消してから、もう一度実行してください")
            config_row = gen_book.append_config_row(values)
            print(f"{c}用スプレッドシートの実行設定 {config_row}行目に予約しました。GAS で生成します")
            runners[c].run()
            text = sc.wait_generated(gen_book, config_row, sc.status_column(c),
                                     settings.get("generate_timeout_min", 30) * 60, 15, print)
            sheets = sc.output_sheets(text)
            if text.startswith("❌") or not sheets:
                raise RuntimeError(f"生成に失敗しました: {text}")
            print(f"生成しました: {', '.join(sheets)}")
            for name in sheets:
                print(f"\n--- チェック: {name} ---")
                if cmd_check(SimpleNamespace(sheet=name, csv=None, no_ai=not settings.get("require_ai_check"),
                                             one_segment=True, spreadsheet_id=t["spreadsheet_id"])) == 2:
                    raise RuntimeError(f"{name} のチェック結果が NG のため入稿しません。レポートを確認してください")
                if p.company in takedown_companies and p.company not in takedown_done:
                    takedown_done[p.company] = _takedown(p.company, settings, args.headed, args.dry_run)
                if isinstance(takedown_done.get(p.company), Exception):
                    raise RuntimeError(f"前回分の取り下げに失敗したため、入稿しません: {takedown_done[p.company]}")
                print(f"\n--- 入稿: {name} ---")
                if cmd_upload(SimpleNamespace(sheet=name, dry_run=args.dry_run, headed=args.headed, yes=True, company=p.company,
                                              spreadsheet_id=t["spreadsheet_id"])) != 0:
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
    print(f"\n完了: {len(targets) + len(td_targets) - failed}件 成功 / {failed}件 失敗")
    return 0 if not failed else 2


def _generate_locally(p, c, t, settings, rules, today, run_id, args, record_usage=True, ignore_cooldown=False):
    """GAS を使わず、ツールで予約1行分の原稿を作る。実行設定シートは使わない（入稿予定表の値から直接作る）。"""
    from . import generator, schedule as sc
    from .checks import Manuscript
    from .qmate_headers import QMATE_HEADERS

    v = dict(zip(sc.CONFIG_FIELDS[c], sc.config_row(p, c, t, rules, today, run_id, args.status, args.count)))
    req = generator.Request(
        category=v["職種番号"], company=v["会社名"], count=int(v["原稿数"]) if v["原稿数"] else None, commute=c,
        employment=v["雇用形態"], update_type=v["更新種別"], status=v["ステータス"], image_category=v["画像カテゴリー"],
        salary_pattern=v["給与パターン"], night=v["夜勤の有無"], standby_keyword=v["スタンバイキーワード"],
        title_measure=v.get("タイトル(施策)", ""), box_word=v["求人ボックスワード"], title_choice=v["職種名選択"],
        created=today)
    print(f"ツールで原稿を生成します（{c}用の土台を使用）")
    result = generator.run(settings, t, req, record_usage=record_usage, ignore_cooldown=ignore_cooldown,
                           dorm=c == "入寮")
    for w in result.warnings:
        print(w)
    name = f"出力_G予定{p.row}_{run_id}_{p.company}_{p.category}_{today:%Y%m%d}"
    table = [QMATE_HEADERS] + [[r[h] for h in QMATE_HEADERS] for r in result.rows]
    print(f"生成しました: {name}（{len(result.rows)}件）")
    if t.get("write_output_sheet"):
        _spreadsheet(dict(settings, spreadsheet_id=t["spreadsheet_id"])).write_output_sheet(name, table)
    return Manuscript(name, table)


def _check_and_upload(manuscripts, p, t, settings, args, takedown_companies, takedown_done) -> None:
    for ms in manuscripts:
        print(f"\n--- チェック: {ms.name} ---")
        if cmd_check(SimpleNamespace(sheet=ms.name, csv=None, no_ai=not settings.get("require_ai_check"),
                                     one_segment=True, spreadsheet_id=t["spreadsheet_id"], manuscript=ms)) == 2:
            raise RuntimeError(f"{ms.name} のチェック結果が NG のため入稿しません。レポートを確認してください")
        if p.company in takedown_companies and p.company not in takedown_done:
            takedown_done[p.company] = _takedown(p.company, settings, args.headed, args.dry_run)
        if isinstance(takedown_done.get(p.company), Exception):
            raise RuntimeError(f"前回分の取り下げに失敗したため、入稿しません: {takedown_done[p.company]}")
        print(f"\n--- 入稿: {ms.name} ---")
        if cmd_upload(SimpleNamespace(sheet=ms.name, dry_run=args.dry_run, headed=args.headed, yes=True, company=p.company,
                                      spreadsheet_id=t["spreadsheet_id"], manuscript=ms)) != 0:
            raise RuntimeError(f"{ms.name} の入稿に失敗しました")


def _takedown(company: str, settings: dict, headed: bool, dry_run: bool, **filters):
    """1社分の取り下げ。結果の dict か、失敗したときは例外を返す（同じ会社の次の行でも使う）。

    filters は takedown.run の date_from・date_to・memo・export_status（取り下げ予定表の行の指定）。
    """
    from . import takedown

    print(f"\n--- 取り下げ: {company} ---")
    try:
        result = takedown.run(company, settings, config.OUTPUT_DIR, headed=headed, dry_run=dry_run, **filters)
    except Exception as e:
        print(f"取り下げに失敗しました: {e}")
        return e
    if not dry_run:
        _record_takedown(result)
    return result


def _record_takedown(result: dict) -> None:
    history = _state("takedown.json")
    history.setdefault(result["company"], []).append(result)
    _save_state("takedown.json", history)


def cmd_takedown(args) -> int:
    from . import takedown

    settings = config.load("settings.json")
    td = settings["takedown"]
    date_from = date.fromisoformat(args.date or args.date_from) if (args.date or args.date_from) else None
    date_to = date.fromisoformat(args.date or args.date_to) if (args.date or args.date_to) else None
    status = args.status or td["export_status"]
    if not args.yes and not args.dry_run and input(
            f"{args.company} の Q-mate にある「{status}」の原稿のうち、{takedown.describe(date_from, date_to)}"
            f"{f'・メモに「{args.memo}」を含む' if args.memo else ''}ものを「{td['update_type']}」します。"
            "元には戻せません。よろしいですか？ [y/N] > ").strip().lower() != "y":
        print("中止しました")
        return 1
    try:
        result = takedown.run(args.company, settings, config.OUTPUT_DIR, headed=args.headed, dry_run=args.dry_run,
                              date_from=date_from, date_to=date_to, memo=args.memo or "", export_status=status)
    except Exception as e:
        print(f"失敗: {e}")
        return 2
    if args.dry_run:
        print("--dry-run のため、取り込みはしていません")
    else:
        _record_takedown(result)
        print(f"取り下げました: {result['count']}件")
    return 0


def _find_commute(settings: dict, sheet: str) -> str | None:
    """出力シートがある方（通勤用・入寮用）を探す。"""
    for c, t in settings["schedule_targets"].items():
        if t.get("base_spreadsheet_id") and sheet in _spreadsheet(dict(settings, spreadsheet_id=t["spreadsheet_id"])).output_sheet_names():
            return c
    return None


def cmd_compare(args) -> int:
    """GAS で作った出力シートと、同じ予約内容でツールが作った原稿（入稿・使用履歴の記録はしない）を見比べる。

    予約内容は、実行設定シートで「実行状況」にその出力シート名が書かれている行から読む。
    """
    from . import generator, schedule as sc
    from .checks import Manuscript
    from .compare import compare
    from .qmate_headers import QMATE_HEADERS

    settings = config.load("settings.json")
    c = args.commute or _find_commute(settings, args.gas_sheet)
    if not c:
        print(f"「{args.gas_sheet}」が、通勤用・入寮用どちらのスプレッドシートにも見つかりません")
        return 1
    t = settings["schedule_targets"][c]
    if not t.get("base_spreadsheet_id"):
        print(f"{c}用は、まだツールでの生成に対応していません（settings.json の base_spreadsheet_id がありません）")
        return 1
    main_book = _spreadsheet(dict(settings, spreadsheet_id=t["spreadsheet_id"]))
    table = main_book.config_table()
    status_col = sc.status_column(c) - 1
    found = next((r for r in table[sc.CONFIG_DATA_START_ROW - 1:]
                  if len(r) > status_col and args.gas_sheet in str(r[status_col])), None)
    if found is None:
        print(f"実行設定に、実行状況が「→ {args.gas_sheet}」の行が見つかりません（この出力シートを作った予約が分かりません）")
        return 1
    v = dict(zip(sc.CONFIG_FIELDS[c], [found[i] if i < len(found) else "" for i in range(len(sc.CONFIG_FIELDS[c]))]))
    v = {k: generator.text(x).strip() for k, x in v.items()} | {"作成日": found[1]}
    gas = main_book.manuscript(args.gas_sheet)
    created = sc.parse_date(v["作成日"], date.today()) or date.today()
    req = generator.Request(
        category=v["職種番号"], company=v["会社名"], count=len(gas.rows), commute=v["通勤か入寮か"] or c,
        employment=v["雇用形態"], update_type=v["更新種別"], status=v["ステータス"], image_category=v["画像カテゴリー"],
        salary_pattern=v["給与パターン"], night=v["夜勤の有無"], standby_keyword=v["スタンバイキーワード"],
        title_measure=v.get("タイトル(施策)", ""), box_word=v["求人ボックスワード"], title_choice=v["職種名選択"],
        created=created)
    print(f"予約内容: {v['会社名']} / {v['職種番号']} / {v['夜勤の有無']} / 給与 {v['給与パターン'] or '指定なし'} / "
          f"{v.get('タイトル(施策)', '')} / 求人ボックスワード {v['求人ボックスワード'] or '空欄'} / {len(gas.rows)}件")
    print("ツールで同じ内容の原稿を作ります（入稿・使用履歴の記録はしません）")
    result = generator.run(settings, t, req, record_usage=False, ignore_cooldown=True, dorm=c == "入寮")
    tool = Manuscript(f"比較_{args.gas_sheet}", [QMATE_HEADERS] + [[r[h] for h in QMATE_HEADERS] for r in result.rows])
    lines, diff = compare(gas, tool)
    out = config.OUTPUT_DIR / f"比較_{args.gas_sheet}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "比較結果.txt").write_text("\n".join(lines), encoding="utf-8")
    (out / "ツールで作った原稿.csv").write_bytes(to_csv_bytes(tool, **settings["csv"]))
    (out / "GASで作った原稿.csv").write_bytes(to_csv_bytes(gas, **settings["csv"]))
    print("\n".join(lines))
    print(f"\nGAS {len(gas.rows)}件 ／ ツール {len(tool.rows)}件。作りが違う列: {diff}列")
    print(f"結果: {out / '比較結果.txt'}")
    return 0 if diff == 0 else 2


def cmd_login_test(args) -> int:
    """登録した会社のログイン情報で、Q-mate にログインして CSV取込画面を開けるか確かめる（何も変えない）。"""
    from .accounts import qmate_config
    from .uploader import QmateUploader

    settings = config.load("settings.json")
    try:
        cfg = qmate_config(settings, args.company)
        print(f"{args.company} のログイン情報で Q-mate にログインします（{cfg['upload_url']}）")
        title = QmateUploader(cfg, headless=not args.headed,
                              out_dir=config.OUTPUT_DIR / f"ログイン確認_{args.company}").check_login()
    except Exception as e:
        print(f"失敗: {e}")
        return 2
    print(f"成功: CSV取込画面を開けました: {title}")
    print("画面のアドレスの co= の番号が、この会社のものか確かめてください")
    return 0


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
    u.add_argument("--company", help="入稿先の会社（省略時は settings.json の qmate.company）")
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
    s.add_argument("--no-takedown", action="store_true", help="入稿前の前回分の取り下げをしない")
    s.add_argument("--takedown-row", type=int, help="取り下げ予定表のこの行だけを、実行日に関係なく実行する")
    s.set_defaults(func=cmd_schedule)

    cp = sub.add_parser("compare", help="GAS で作った出力シートと、ツールで作った原稿を見比べる")
    cp.add_argument("--gas-sheet", required=True, help="GAS が作った出力シートの名前")
    cp.add_argument("--commute", help="通勤 か 入寮（どちらのスプレッドシートの出力か。省略時は自動で探す）")
    cp.set_defaults(func=cmd_compare)

    lt = sub.add_parser("login-test", help="会社のログイン情報で Q-mate にログインできるか確かめる")
    lt.add_argument("--company", required=True, help="会社名")
    lt.add_argument("--headed", action="store_true", help="ブラウザを表示して動かす")
    lt.set_defaults(func=cmd_login_test)

    t = sub.add_parser("takedown", help="今 Q-mate に載っている原稿を取り下げる（削除する）")
    t.add_argument("--company", required=True, help="会社名")
    t.add_argument("--date", help="求人メモの作成日がこの日の原稿だけ（YYYY-MM-DD）")
    t.add_argument("--from", dest="date_from", help="求人メモの作成日がこの日から（YYYY-MM-DD）")
    t.add_argument("--to", dest="date_to", help="求人メモの作成日がこの日まで（YYYY-MM-DD）")
    t.add_argument("--memo", help="メモにこの文字を含む原稿だけ")
    t.add_argument("--status", help="取り出すステータス（省略時は settings.json の takedown.export_status）")
    t.add_argument("--dry-run", action="store_true", help="取り出しとファイル分けまでで止める（Q-mate は変えない）")
    t.add_argument("--headed", action="store_true", help="ブラウザを表示して動かす")
    t.add_argument("--yes", action="store_true", help="実行前の確認を省く")
    t.set_defaults(func=cmd_takedown)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
