"""ヒトマネ入稿ツールのコマンド。

  python -m hitomane_agent companies                                    会社の一覧（ログイン情報シートの会社の行）
  python -m hitomane_agent survey --company 会社 [--headed] [--sample [募集番号]]   管理画面の画面調査
  python -m hitomane_agent login (--company 会社 | --all)               ログインの確認と募集管理の全件数・拠点
  python -m hitomane_agent list                                         出力シートの一覧とチェックの状態
  python -m hitomane_agent plan-sheet                                   入稿予定表のシートを作る・整える
  python -m hitomane_agent schedule [--row 5] [--dry-run] [--yes]       入稿予定表の今日の行を、作る → チェック → 入稿
  python -m hitomane_agent plan                                         予約リスト（ヒトマネ実行設定）のグループ
  python -m hitomane_agent generate (--group 1 [--group 2 …] | --all)   ツールで原稿を作る（入稿・使用履歴の記録はしない）
  python -m hitomane_agent compare --generated ツール_… [--gas-sheet ヒトマネ出力_…]   GAS の原稿と見比べる
  python -m hitomane_agent check (--sheet 名前 | --csv パス | --generated ツール_…)   入稿前のチェック
  python -m hitomane_agent upload --company 会社 (--sheet 名前 | --csv パス | --generated ツール_…) [--yes] [--dry-run]   ヒトマネに取り込む
  python -m hitomane_agent takedown --company 会社 --from 2026/10/01 --to 2026/10/31 [--prepare-only] [--yes]   取り下げ

ヒトマネは会社ごとに管理画面の URL が違う（ID・パスワードは同じ）。--company は会社名・会社のコード（o3h3 など）・会社名の一部のどれでもよい。
会社が1社しかないときと、settings.local.json に "company" を書いたときは省ける。
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import accounts, charfix, config, workflow


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
    if getattr(args, "generated", None):
        from . import generated
        return generated.load(args.generated)
    return workflow.load_manuscript(settings, sheet=args.sheet, csv=args.csv)


def _books(settings):
    import gspread

    from . import generator
    gc = gspread.service_account(filename=str(config.ROOT / settings["service_account_file"]))
    return gc.open_by_key(generator.BASE_SPREADSHEET_ID), gc.open_by_key(settings["spreadsheet_id"])


def _shisaku_books(settings, need_bunrui: bool):
    """施策用の土台と、6重め/7軽めを作るときの ＜ヒトマネ＞重め軽め職種分類 の読み方（読めなければ None と理由）。"""
    import gspread

    from . import shisaku
    path = config.ROOT / settings["service_account_file"]
    gc = gspread.service_account(filename=str(path))
    base = gc.open_by_key(shisaku.BASE_SPREADSHEET_ID)
    if not need_bunrui:
        return base, None, ""
    try:
        return base, shisaku.bunrui_reader(gc.open_by_key(shisaku.BUNRUI_SPREADSHEET_ID)), ""
    except Exception as e:
        import json
        who = json.loads(path.read_text(encoding="utf-8")).get("client_email", "ツールの読み取り用アカウント")
        return base, None, (f"＜ヒトマネ＞重め軽め職種分類 を読めませんでした（{type(e).__name__}）。"
                            f"{who} に閲覧の共有が必要です")


def cmd_plan(args) -> int:
    from . import generator

    settings = _settings(args)
    _, ai = _books(settings)
    targets = generator.read_targets(generator.load_config(ai), include_done=True)
    if not targets:
        print("予約リスト（ヒトマネ実行設定）に行がありません")
    for gid, ts in generator.groups_of(targets).items():
        counts = "+".join(t.count_raw or "勤務地数" for t in ts)
        done = "、".join(sorted({t.exec_status[:20] for t in ts if t.exec_status})) or "未実行"
        print(f"グループ {gid}: {ts[0].company}・{ts[0].category}・{ts[0].format}・{len(ts)}行（{counts}）・GAS：{done}")
    return 0


def cmd_generate(args) -> int:
    """予約リストのグループを、ツールで原稿にする（GAS の③の代わり）。スプレッドシートには何も書かない。"""
    from . import generated, generator

    settings, rules = _settings(args), config.load("rules.json")
    if not args.all and not args.group:
        print("作るグループを --group で指定してください（全部なら --all）")
        return 1
    base, ai = _books(settings)
    print("土台と予約リストを読んでいます…")
    grids, usage = generator.load_base(base)
    bank = generator.build_bank(grids)
    targets = generator.read_targets(generator.load_config(ai), include_done=args.include_done)
    known = set(generator.groups_of(targets))
    wanted = None if args.all else set(args.group)
    if wanted and wanted - known:
        print(f"予約リストにないグループです：{'、'.join(sorted(wanted - known))}（あるもの：{'、'.join(known) or 'なし'}）"
              + ("" if args.include_done else "。GAS で実行済みの行も使うときは --include-done を付けてください"))
        return 1
    from . import plan
    results = generator.run(bank, plan.merge_usage(usage), targets, only_groups=wanted)
    code = 0
    for r in results:
        if r.error:
            print(f"\nグループ {r.group_id}：作れませんでした：{r.error}")
            code = 2
            if not r.rows:
                continue
        name = generated.save(r, {"source": "ヒトマネ実行設定"})
        fixed = generated.meta(name).get("replaced")
        if fixed:
            print(f"\nグループ {r.group_id}：書けない記号を置き換えました：{charfix.summary(fixed)}")
        res = workflow.check(generated.load(name), rules)
        print(f"\nグループ {r.group_id}：{name}\n  原稿 {len(r.rows)}件、チェック {res['status']}（"
              + "、".join(f"{k} {v}件" for k, v in res["counts"].items()) + "）")
        for i in res["sheet_issues"]:
            print(f"  シート全体: {i['message']}")
        print(f"  チェック表: {res['report']}")
        if r.skipped:
            print(f"  作らなかった予約行：{'、'.join(r.skipped)}")
        if res["status"] == "NG":
            code = 2
    print("\n使用履歴には書いていません（確かめている間は読むだけ）。")
    return code


def cmd_plan_sheet(args) -> int:
    """【AI用】に入稿予定表のシートを作る（あれば見出しとプルダウンを整える。入っている予定は消さない）。"""
    from . import generator, plan

    settings = _settings(args)
    base, ai = _books(settings)
    grids, _ = generator.load_base(base)
    sbase = reader = None
    try:  # 職種名指定・市区町村の候補は施策の土台、6重め/7軽めは分類ブックから
        from . import shisaku
        book, reader, why = _shisaku_books(settings, need_bunrui=True)
        sbase = shisaku.load_base(book)
        if why:
            print(why)
    except Exception as e:
        print(f"施策の土台を読めませんでした：{e}")
    for line in plan.setup_sheet(ai, generator.build_bank(grids), sbase, reader):
        print(line)
    return 0


def cmd_schedule(args) -> int:
    """入稿予定表の今日の行（--row ならその行）を、作る → チェック → 入稿 → 実行結果を書く、まで行う。"""
    from datetime import date

    from . import generated, generator, plan

    settings, rules = _settings(args), config.load("rules.json")
    today = date.fromisoformat(args.date) if args.date else date.today()
    base, ai = _books(settings)
    try:
        rows = plan.read_plan(ai.worksheet(plan.SHEET).get_all_values(), today)
    except Exception as e:
        print(f"入稿予定表を読めませんでした：{e}")
        return 1
    targets = [p for p in rows if p.row in args.row] if args.row else [p for p in rows if p.run_date == today]
    if not args.force:
        finished = plan.done()
        for p in [p for p in targets if p.key in finished]:
            print(f"入稿予定表 {p.row}行目は {finished[p.key]['finished_at']} に実行済みです（やり直すときは --force）")
        targets = [p for p in targets if p.key not in finished]
    if not targets:
        print(f"入稿予定表に、{today:%Y/%m/%d} に実行する行がありません" if not args.row else "実行する行がありません")
        return 0
    infos = {}
    if not args.dry_run:
        cs = accounts.companies(settings)
        for p in targets:
            if p.company not in infos:
                try:
                    c = accounts.find_company(cs, p.company)
                    infos[p.company] = accounts.login_info(settings, company=c["code"])
                except Exception as e:
                    print(f"{p.row}行目：{p.company} の入稿先が分かりません：{e}")
                    return 1
    print(f"入稿予定表から {len(targets)}件 を{'テスト（作ってチェックするだけ）' if args.dry_run else '実行'}します")
    for p in targets:
        to = f" → {accounts.label(infos[p.company])}" if p.company in infos else ""
        how = f"施策・{p.fmt}" + "".join(f"・{v}" for v in (p.title_spec, p.bunrui, p.pref + p.city) if v) \
            if p.shisaku else "通常"
        print(f"  {p.row}行目: {p.company} / {p.category} / {'夜勤あり' if p.night else '夜勤なし'} / {p.commute} / "
              f"{p.count or '勤務地の数'}件 / {p.status} / {how}{to}")
    if not args.dry_run and not args.yes and input("原稿を作ってヒトマネに入稿します。よろしいですか？ [y/N] > ").strip().lower() != "y":
        print("中止しました")
        return 1

    try:
        gen_targets = plan.to_targets(targets, today, plan.entry_numbers())
    except RuntimeError as e:
        print(e)
        return 1
    results = _generate_plan(targets, gen_targets, base, settings, today)
    failed = 0
    for p in targets:
        print(f"\n=== 入稿予定表 {p.row}行目 ===")
        r = results.get(p.row)
        if r is None or r.error or not r.rows:
            text = f"作れませんでした：{r.error if r else '前の行のエラーで止まりました'}"
            ok = False
        else:
            name = generated.save(r, {"source": "入稿予定表", "plan_row": p.row})
            fixed = generated.meta(name).get("replaced")
            if fixed:
                print(f"書けない記号を置き換えました：{charfix.summary(fixed)}")
            ms = generated.load(name)
            res = workflow.check(ms, rules)
            print(f"{name}：原稿 {len(ms.rows)}件、チェック {res['status']}（{res['report']}）")
            if res["status"] == "NG":
                text, ok = f"チェックが NG のため入稿しません（{datetime.now():%m/%d %H:%M}）{name}", False
            elif args.dry_run:
                text, ok = f"テスト済み（{datetime.now():%m/%d %H:%M}）{len(ms.rows)}件・チェック {res['status']} {name}", True
            else:
                paths = workflow.write_csvs(ms, settings, rules)
                code, text = _import(ms, infos[p.company], paths, settings, rules, args.headed, stop_over_limit=True)
                ok = code == 0
                if ok:
                    text += f" {name}"
                    plan.mark_done(p, text)
        print(text)
        failed += 0 if ok else 1
        if not args.dry_run:
            try:
                plan.write_result(ai, p.row, ("" if ok else "❌") + text)
            except Exception as e:
                print(f"（実行結果を入稿予定表に書けませんでした：{e}）")
    print(f"\n{len(targets)}件中 {len(targets) - failed}件 {'テストできました' if args.dry_run else '入稿しました'}")
    return 0 if not failed else 2


def _generate_plan(plans, gen_targets, base, settings, today) -> dict:
    """入稿予定表の行を、作り方（通常/施策）ごとの作り方で、上の行から順に作る。{行: GroupResult}。

    募集番号は、作り方が違っても同じ会社なら前の行の続きを使う。使う土台だけを読む。"""
    from . import generator, plan, shisaku

    results, bank, usage, sbase, reader, why = {}, None, None, None, None, ""
    if any(not p.shisaku for p in plans):
        print("\n土台を読んでいます…")
        grids, usage = generator.load_base(base)
        bank, usage = generator.build_bank(grids), plan.merge_usage(usage)
    if any(p.shisaku for p in plans):
        print("施策用の土台を読んでいます…")
        need = any(p.shisaku and generator._content_category(p.category) in ("重め", "軽め") for p in plans)
        sbook, reader, why = _shisaku_books(settings, need)
        sbase = plan.merge_shisaku_usage(shisaku.load_base(sbook))
    continuation = {}
    for p, t in zip(plans, gen_targets):
        problem = p.problem()
        if problem:
            results[p.row] = generator.GroupResult(t.group_id, "", p.company, p.category, [t], error=problem)
            continue
        if p.shisaku:
            if reader is None and why and generator._content_category(p.category) in ("重め", "軽め"):
                results[p.row] = generator.GroupResult(t.group_id, "", p.company, p.category, [t], error=why)
                continue
            rs = shisaku.run(sbase, [t], reader, today=today, continuation=continuation)
        else:
            rs = generator.run(bank, usage, [t], today=today, stop_on_error=False, continuation=continuation)
        if rs:
            results[p.row] = rs[0]
    return results


def cmd_compare(args) -> int:
    from . import compare, generated
    from .sheet import Spreadsheet

    settings = _settings(args)
    tool = generated.load(args.generated)
    gas_name = args.gas_sheet or generated.gas_name_for(args.generated)
    try:
        gas = Spreadsheet(settings).manuscript(gas_name)
    except Exception:
        print(f"GAS の原稿のシート「{gas_name}」が【AI用】にありません。GAS で③を回してから比べてください")
        return 1
    lines, diff = compare.compare(gas, tool)
    print(f"GAS：{gas_name}\nツール：{args.generated}\n")
    print("\n".join(lines))
    print(f"\n違いのあった列：{diff}")
    return 0 if diff == 0 else 2


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
    ask = None if args.yes else (lambda: input(f"{accounts.label(info)} に取り込みますか？ [y/N] > ").strip().lower() == "y")
    code, _ = _import(ms, info, paths, settings, rules, args.headed, ask)
    return code


def _import(ms, info, paths, settings, rules, headed=False, ask=None, stop_over_limit=False) -> tuple[int, str]:
    """ログインして全件数・拠点を確かめてから取り込む。（終了コード, 実行結果の一言）。"""
    from .uploader import HitomaneUploader

    key = accounts.account_key(info)
    up = HitomaneUploader(info, settings["hitomane"], config.OUTPUT_DIR / ms.name, headed=headed)
    acct = up.account()
    workflow.save_total(key, acct["total"], info.get("company", ""))
    stop = workflow.branch_problem(ms, acct["branches"], info.get("company", ""))
    if not stop and stop_over_limit and acct["total"] is not None and acct["total"] + len(ms.rows) > rules["total_limit"]:
        stop = (f"募集管理の全件数 {acct['total']:,}件に {len(ms.rows):,}件を足すと上限 {rules['total_limit']:,}件を超えます。"
                "先に取り下げてください")
    if stop:
        print(f"入稿しません: {stop}")
        return 1, f"入稿しません：{stop}"
    print(workflow.total_note(acct["total"], len(ms.rows), rules))
    if ask is not None and not ask():
        print("中止しました")
        return 1, "中止しました"
    results = up.upload(paths, old_format=ms.is_old_format)
    workflow.record_upload(ms, results, key, info.get("company", ""))
    ok = bool(results) and all(r.ok for r in results) and len(results) == len(paths)
    for r in results:
        print(f"{'成功' if r.ok else '失敗'}: {r.file} {r.message}\n  {r.row_text}\n  画面: {r.screenshot}")
    if len(results) < len(paths):
        print(f"失敗したため、残りの {len(paths) - len(results)} ファイルは取り込んでいません")
    from . import generated, plan
    if ok and generated.exists(ms.name):
        meta = generated.meta(ms.name)
        plan.record_usage(meta)  # 次に作るときに、入稿した職種名・仕事内容を避ける（このパソコンの記録）
        if ms.rows:
            plan.remember_number(meta["company"], ms.rows[-1].get("募集番号", ""))
    if ok:
        return 0, f"入稿済み（{datetime.now():%m/%d %H:%M}）{len(ms.rows)}件 → {accounts.label(info)}"
    return 2, f"入稿が途中で止まりました（{datetime.now():%m/%d %H:%M}）取込ファイル一覧を確かめてください"


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

    s = sub.add_parser("plan", help="予約リスト（ヒトマネ実行設定）のグループを見る")
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("generate", help="予約リストのグループをツールで原稿にする（入稿・使用履歴の記録はしない）")
    s.add_argument("--group", action="append", help="作るグループ番号（1-1, 1-2 … の「1」）。何度でも指定できる")
    s.add_argument("--all", action="store_true", help="GAS がまだ実行していない全部のグループ")
    s.add_argument("--include-done", action="store_true", help="GAS で実行済み（実行状況の入った）行も使う")
    s.set_defaults(func=cmd_generate)

    s = sub.add_parser("plan-sheet", help="【AI用】に入稿予定表のシートを作る・整える（見出しとプルダウン。予定は消さない）")
    s.set_defaults(func=cmd_plan_sheet)

    s = sub.add_parser("schedule", help="入稿予定表の今日の行を、作る → チェック → 入稿 → 実行結果を書く、まで行う")
    s.add_argument("--row", type=int, action="append", help="この行だけ（入稿予定表の行番号。何度でも指定できる）")
    s.add_argument("--date", help="今日の代わりにこの日の行（2026-11-20 の形）")
    s.add_argument("--dry-run", action="store_true", help="テスト：作ってチェックするだけ（入稿しない。予定表にも書かない）")
    s.add_argument("--force", action="store_true", help="実行済みの行もやり直す")
    s.add_argument("--yes", action="store_true", help="確認を聞かずに入稿する")
    s.add_argument("--headed", action="store_true", help="ブラウザを表示して動かす")
    s.set_defaults(func=cmd_schedule)

    s = sub.add_parser("compare", help="GAS で作った原稿とツールで作った原稿を列ごとに見比べる")
    s.add_argument("--generated", required=True, help="ツールで作った原稿（ツール_…）")
    s.add_argument("--gas-sheet", help="GAS の原稿のシート名（省くと同じ予約の ヒトマネ出力_…）")
    s.set_defaults(func=cmd_compare)

    for name, func, text in (("check", cmd_check, "入稿前のチェック"), ("upload", cmd_upload, "ヒトマネに取り込む")):
        s = sub.add_parser(name, help=text)
        g = s.add_mutually_exclusive_group(required=True)
        g.add_argument("--sheet", help="出力シートの名前（ヒトマネ出力_…）")
        g.add_argument("--csv", help="シートの代わりに読む CSV（取り出した CSV をそのまま取り込み直すときなど）")
        g.add_argument("--generated", help="ツールで作った原稿（ツール_…。generate で作ったもの）")
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
