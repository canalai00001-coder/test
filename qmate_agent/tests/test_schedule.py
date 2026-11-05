"""入稿予定表からの実行（schedule）を確かめる。スプレッドシート・GAS・Q-mate には接続しない。"""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from qmate_agent import __main__ as cli
from qmate_agent import config
from qmate_agent import schedule as sc

RULES = config.load("rules.json")
TARGETS = config.load("settings.json")["schedule_targets"]
TODAY = date(2026, 10, 30)
HEAD = ["実行日", "会社", "職種", "夜勤有無", "通勤/入寮", "雇用形態", "入稿ステータス", "原稿数",
        "スタンバイキーワード\n(空欄=自動選択)", "求人ボックスワード", "職種名選択\n(6重め/7軽めのみ・必須)", "実行結果"]
PLAN = [
    HEAD,
    ["", "AspiRove株式会社", "1クルマ", "TRUE", "通勤", "正社員", "下書き", "500"],
    ["2026/10/30", "AspiRove株式会社", "8梱包", "FALSE", "通勤", "契約社員", "", "1,000"],
    ["10/31", "AspiRove株式会社", "5半導体", "FALSE", "", "", "", "200"],
    ["", "", "", "FALSE"],
]
DORM = ["2026/10/30", "AspiRove株式会社", "7軽め", "FALSE", "入寮", "", "", "900", "急募で新生活へ", "仕事探し寮付き",
        "防犯カメラの検査"]


def as_dict(plan, commute, **kw):
    return dict(zip(sc.CONFIG_FIELDS[commute], sc.config_row(plan, commute, TARGETS[commute], RULES, TODAY, "0900", **kw)))


class TestPlan(unittest.TestCase):
    def test_read_plan(self):
        rows = sc.read_plan(PLAN, TODAY)
        self.assertEqual([(p.row, p.run_date, p.category, p.night, p.count) for p in rows], [
            (2, None, "1クルマ", True, 500),
            (3, date(2026, 10, 30), "8梱包", False, 1000),
            (4, date(2026, 10, 31), "5半導体", False, 200),
        ])
        self.assertEqual([(p.commute, p.employment, p.status) for p in rows], [
            ("通勤", "正社員（人材紹介）", "下書き"), ("通勤", "契約社員（人材紹介）", ""), ("", "", "")])

    def test_unformatted_values_from_sheet(self):
        # シートから書式なしで読むと、日付はシリアル値、数値は数、チェックボックスは真偽値になる
        rows = sc.read_plan([HEAD, [46328, "AspiRove株式会社", "1クルマ", True, "通勤", "正社員", "下書き", 50]], TODAY)
        self.assertEqual((rows[0].run_date, rows[0].night, rows[0].count), (date(2026, 11, 2), True, 50))

    def test_old_layout_without_new_columns(self):
        rows = sc.read_plan([["実行日", "会社", "職種", "夜勤有無", "原稿数"], ["", "A社", "1クルマ", "TRUE", "5"]], TODAY)
        self.assertEqual((rows[0].count, rows[0].commute, rows[0].title_choice), (5, "", ""))

    def test_salary_pattern_from_floor(self):
        self.assertEqual(sc.salary_pattern("1クルマ", True, RULES, "基本"), "35万")
        self.assertEqual(sc.salary_pattern("8梱包", False, RULES, "基本"), "28万")
        self.assertEqual(sc.salary_pattern("2工場", True, RULES, "基本"), "基本")

    def test_commute_row(self):
        row = as_dict(sc.read_plan(PLAN, TODAY)[0], "通勤", status="下書き", count=5)
        self.assertEqual(row["グループ番号"], "予定2_0900-1")
        self.assertEqual((row["作成日"], row["職種番号"], row["会社名"], row["原稿数"]), ("2026/10/30", "1クルマ", "AspiRove株式会社", 5))
        self.assertEqual((row["ステータス"], row["夜勤の有無"], row["給与パターン"]), ("下書き", "夜勤あり", "35万"))
        self.assertEqual((row["通勤か入寮か"], row["雇用形態"], row["タイトル(施策)"]), ("通勤", "正社員（人材紹介）", "タイトル2(施策)"))
        self.assertEqual(len(row), 16)
        self.assertEqual(sc.status_column("通勤"), 17)

    def test_dorm_row_uses_dorm_layout(self):
        plan = sc.read_plan([HEAD, DORM], TODAY)[0]
        self.assertEqual(sc.commute_of(plan, "通勤"), "入寮")
        row = as_dict(plan, "入寮")
        self.assertNotIn("タイトル(施策)", row)
        self.assertEqual(len(row), 15)
        self.assertEqual(sc.status_column("入寮"), 16)
        self.assertEqual((row["通勤か入寮か"], row["雇用形態"], row["画像カテゴリー"], row["給与パターン"]),
                         ("入寮", "契約社員（人材紹介）", "入寮", ""))
        self.assertEqual(row["職種名選択"], "7軽め｜防犯カメラの検査")
        self.assertEqual((row["スタンバイキーワード"], row["求人ボックスワード"]), ("急募で新生活へ", "仕事探し寮付き"))

    def test_header_name(self):
        self.assertEqual(sc.header_name("職種名選択\n(6重め/7軽めのみ・必須)"), "職種名選択")
        self.assertEqual(sc.header_name("スタンバイキーワード（空欄=自動選択）"), "スタンバイキーワード")
        self.assertEqual(sc.header_name(" 通勤/入寮 "), "通勤/入寮")

    def test_blank_words_use_defaults(self):
        row = as_dict(sc.read_plan(PLAN, TODAY)[0], "通勤")
        self.assertEqual((row["スタンバイキーワード"], row["求人ボックスワード"]), ("", "遠方からの応募可能"))

    def test_blank_commute_uses_default(self):
        plan = sc.read_plan(PLAN, TODAY)[2]
        self.assertEqual(sc.commute_of(plan, "通勤"), "通勤")
        with self.assertRaises(ValueError):
            sc.commute_of(sc.PlanRow(2, None, "A社", "1クルマ", False, 5, commute="寮"), "通勤")

    def test_heavy_light_need_title_choice(self):
        with self.assertRaises(ValueError):
            sc.config_row(sc.PlanRow(2, None, "A社", "6重め", True, 5), "通勤", TARGETS["通勤"], RULES, TODAY, "0900")

    def test_row_ranges(self):
        self.assertEqual(sc.row_ranges([4, 5, 6, 9]), "4〜6、9")
        self.assertEqual(sc.row_ranges([7]), "7")

    def test_output_sheets(self):
        self.assertEqual(sc.output_sheets("✅完了(2026-10-30 09:01) 500件 → 出力_A, 出力_B"), ["出力_A", "出力_B"])
        self.assertEqual(sc.output_sheets("❌エラー: 会社名が空です"), [])


class FakeBook:
    """入稿予定表のある本体と、生成先のスプレッドシートを兼ねる。"""

    def __init__(self, status, plan=None, pending=None, takedown_plan=None):
        self.status, self.plan, self.pending = status, plan or PLAN, pending or []
        self.takedown_plan = takedown_plan or []
        self.appended, self.results, self.status_cols, self.takedown_results = [], {}, [], {}

    def pending_config_rows(self, col):
        return self.pending

    def plan_table(self, sheet=None):
        return self.takedown_plan if sheet == "取り下げ予定表" else self.plan

    def append_config_row(self, values):
        self.appended.append(values)
        return 5

    def config_status(self, row, col):
        if row == 1:
            return getattr(self, "overall", "")
        self.status_cols.append(col)
        return self.status

    def write_plan_result(self, row, text, sheet=None):
        (self.takedown_results if sheet == "取り下げ予定表" else self.results)[row] = text


class TestScheduleCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(config, "STATE_DIR", self.tmp / "state"),
                        mock.patch.dict("os.environ", {"QMATE_GAS_TOKEN": "t", "QMATE_GAS_TOKEN_DORM": "d",
                                                        "QMATE_ID": "id", "QMATE_PASSWORD": "pw"}),
                        mock.patch("qmate_agent.accounts.login_problem",
                                   lambda st, c: "" if c in self.registered or c == "AspiRove株式会社"
                                   else f"「{c}」の Q-mate のログイン情報が登録されていません")]
        self.registered = {}
        load = config.load

        self.auto_takedown = False
        self.engine = "gas"

        def settings_with_urls(n):
            if n != "settings.json":
                return load(n)
            s = load(n)
            for c, t in s["schedule_targets"].items():
                t["gas_webapp_url"] = f"https://script.google.com/{c}/exec"
            s["takedown"]["enabled"] = self.auto_takedown
            s["schedule_targets"]["通勤"]["engine"] = self.engine
            return s
        self.patches.append(mock.patch.object(cli.config, "load", settings_with_urls))
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def run_schedule(self, book, check=0, upload=0, takedown=None, **kw):
        args = SimpleNamespace(date="2026-10-30", row=None, status=None, count=None, dry_run=False,
                               headed=False, force=False, yes=True, no_takedown=False, takedown_row=None)
        vars(args).update(kw)
        books = []

        def spreadsheet(settings):
            books.append(settings["spreadsheet_id"])
            return book
        with mock.patch.object(cli, "_spreadsheet", side_effect=spreadsheet), \
                mock.patch.object(sc, "GasRunner") as gas, \
                mock.patch.object(cli, "cmd_check", return_value=check) as c, \
                mock.patch.object(cli, "cmd_upload", return_value=upload) as u, \
                mock.patch.object(cli, "_takedown", return_value=takedown or {"count": 0, "span": "作成日：全期間"}) as td, \
                mock.patch("builtins.print"):
            code = cli.cmd_schedule(args)
        self.takedown = td
        return code, gas, c, u, books

    def test_todays_row_is_generated_checked_and_uploaded(self):
        book = FakeBook("✅完了(2026-10-30 09:01) 1000件 → 出力_G予定3")
        code, gas, c, u, books = self.run_schedule(book)
        self.assertEqual(code, 0)
        self.assertEqual(len(book.appended), 1)
        self.assertEqual(book.appended[0][4], "8梱包")
        self.assertEqual(gas.call_args.args, ("https://script.google.com/通勤/exec", "t"))
        gas.return_value.run.assert_called_once()
        self.assertEqual(c.call_args.args[0].sheet, "出力_G予定3")
        self.assertTrue(c.call_args.args[0].one_segment)
        self.assertEqual(u.call_args.args[0].sheet, "出力_G予定3")
        self.assertEqual(set(books), {TARGETS["通勤"]["spreadsheet_id"]})
        self.assertIn("入稿済み", book.results[3])
        # 同じ行は2回実行しない
        book2 = FakeBook("✅完了 → 出力_G予定3")
        self.assertEqual(self.run_schedule(book2)[0], 0)
        self.assertEqual(book2.appended, [])

    def test_dorm_row_goes_to_dorm_spreadsheet(self):
        book = FakeBook("✅完了 → 出力_G予定2", plan=[HEAD, DORM])
        code, gas, c, u, books = self.run_schedule(book)
        self.assertEqual(code, 0)
        self.assertEqual(gas.call_args.args, ("https://script.google.com/入寮/exec", "d"))
        self.assertEqual(len(book.appended[0]), 15)
        self.assertEqual(book.status_cols[0], 16)
        dorm_id = TARGETS["入寮"]["spreadsheet_id"]
        self.assertIn(dorm_id, books)
        self.assertEqual((c.call_args.args[0].spreadsheet_id, u.call_args.args[0].spreadsheet_id), (dorm_id, dorm_id))

    def test_no_auto_takedown_by_default(self):
        # 今の設定では、入稿予定表の行を入れただけでは取り下げない
        self.assertFalse(config.load("settings.json")["takedown"]["enabled"])
        book = FakeBook("✅完了 → 出力_X")
        self.assertEqual(self.run_schedule(book)[0], 0)
        self.takedown.assert_not_called()

    def test_takedown_once_per_company_before_upload(self):
        # 自動の取り下げを有効にした場合：3行目は入稿ステータス空欄（=公開）。入稿の前に1回だけ取り下げる
        self.auto_takedown = True
        book = FakeBook("✅完了 → 出力_X")
        code, _, _, u, _ = self.run_schedule(book)
        self.assertEqual(code, 0)
        self.takedown.assert_called_once()
        self.assertEqual(self.takedown.call_args.args[0], "AspiRove株式会社")

    def test_draft_rows_do_not_take_down(self):
        # 下書きだけの試運転では、本番の公開原稿を消さない
        self.auto_takedown = True
        book = FakeBook("✅完了 → 出力_X")
        self.run_schedule(book, status="下書き")
        self.takedown.assert_not_called()

    def test_failed_takedown_blocks_upload(self):
        self.auto_takedown = True
        book = FakeBook("✅完了 → 出力_X")
        code, _, _, u, _ = self.run_schedule(book, takedown=RuntimeError("テンプレート出力が失敗しました"))
        self.assertEqual(code, 2)
        u.assert_not_called()
        self.assertIn("取り下げに失敗", book.results[3])

    def test_no_takedown_option(self):
        self.auto_takedown = True
        book = FakeBook("✅完了 → 出力_X")
        self.run_schedule(book, no_takedown=True)
        self.takedown.assert_not_called()

    def test_takedown_only_rows(self):
        # 取り下げ予定表だけに今日の行がある：入稿はせず、指定の期間で取り下げる
        tplan = [["実行日", "会社", "作成日から", "作成日まで", "メモに含む文字", "対象ステータス", "実行結果"],
                 ["2026/10/30", "AspiRove株式会社", "2026/10/01", "2026/10/22", "", "", ""],
                 ["2026/11/01", "AspiRove株式会社", "", "", "", "", ""]]
        book = FakeBook("", plan=[HEAD], takedown_plan=tplan)
        code, gas, c, u, _ = self.run_schedule(book, takedown={"count": 120, "span": "作成日：2026/10/01〜2026/10/22"})
        self.assertEqual(code, 0)
        self.takedown.assert_called_once()
        kw = self.takedown.call_args.kwargs
        self.assertEqual((kw["date_from"], kw["date_to"]), (date(2026, 10, 1), date(2026, 10, 22)))
        gas.return_value.run.assert_not_called()
        self.assertIn("取り下げ済み", book.takedown_results[2])
        self.assertIn("120件", book.takedown_results[2])
        # 2回目は実行済みとして飛ばす
        book2 = FakeBook("", plan=[HEAD], takedown_plan=tplan)
        self.run_schedule(book2)
        self.takedown.assert_not_called()

    def test_takedown_row_replaces_auto_takedown(self):
        # 同じ会社の取り下げ予定表の行があれば、入稿前の自動の取り下げ（全件）はしない
        self.auto_takedown = True
        tplan = [["実行日", "会社", "作成日から", "作成日まで"], ["2026/10/30", "AspiRove株式会社", "2026/10/22", "2026/10/22"]]
        book = FakeBook("✅完了 → 出力_X", takedown_plan=tplan)
        code, _, _, u, _ = self.run_schedule(book)
        self.assertEqual(code, 0)
        self.takedown.assert_called_once()
        self.assertEqual(self.takedown.call_args.kwargs["date_from"], date(2026, 10, 22))
        u.assert_called_once()

    def test_python_engine_generates_without_gas(self):
        # 通勤をツールで生成：GAS も実行設定も使わず、生成した原稿をチェックして入稿する
        from qmate_agent import generator
        from qmate_agent.qmate_headers import QMATE_HEADERS
        self.engine = "python"
        row = {h: "" for h in QMATE_HEADERS}
        row.update({"更新種別|必須": "登録", "職種名|必須": "＜x＞二交代・夜勤なし"})
        seen = {}

        def fake_run(settings, target, req, **kw):
            seen["req"], seen["kw"] = req, kw
            return generator.Result([row, dict(row)], {"x": 2}, [])
        book = FakeBook("")
        with mock.patch.object(generator, "run", fake_run):
            code, gas, c, u, _ = self.run_schedule(book)
        self.assertEqual(code, 0)
        self.assertEqual(book.appended, [])
        gas.return_value.run.assert_not_called()
        self.assertEqual((seen["req"].category, seen["req"].count, seen["req"].salary_pattern), ("8梱包", 1000, "28万"))
        self.assertEqual(seen["kw"], {"record_usage": True, "ignore_cooldown": False, "dorm": False})
        ms = c.call_args.args[0].manuscript
        self.assertEqual(len(ms.rows), 2)
        self.assertIs(u.call_args.args[0].manuscript, ms)
        self.assertIn("入稿済み", book.results[3])

    def test_python_engine_error_is_recorded(self):
        from qmate_agent import generator
        self.engine = "python"
        book = FakeBook("")

        def boom(*a, **k):
            raise ValueError("重複警告: チョークの製造は使用履歴に存在しています。")
        with mock.patch.object(generator, "run", boom):
            code, _, c, u, _ = self.run_schedule(book)
        self.assertEqual(code, 2)
        u.assert_not_called()
        self.assertIn("重複警告", book.results[3])

    def test_row_option_ignores_date(self):
        book = FakeBook("✅完了 → 出力_X")
        self.run_schedule(book, row=2, status="下書き", count=5)
        self.assertEqual(book.appended[0][4], "1クルマ")
        self.assertEqual((book.appended[0][6], book.appended[0][8]), (5, "下書き"))

    def test_ng_stops_before_upload(self):
        book = FakeBook("✅完了 → 出力_X")
        code, _, _, u, _ = self.run_schedule(book, check=2)
        self.assertEqual(code, 2)
        u.assert_not_called()
        self.assertIn("NG", book.results[3])

    def test_generation_error_is_recorded(self):
        book = FakeBook("❌エラー: 会社名が空です")
        code, _, c, _, _ = self.run_schedule(book)
        self.assertEqual(code, 2)
        c.assert_not_called()
        self.assertIn("会社名が空です", book.results[3])

    def test_unregistered_company_is_refused(self):
        book = FakeBook("", plan=[HEAD, ["2026/10/30", "ArK株式会社", "8梱包", "FALSE", "通勤", "", "", "10"]])
        self.assertEqual(self.run_schedule(book)[0], 1)
        self.assertEqual(book.appended, [])

    def test_registered_company_is_uploaded_with_its_name(self):
        self.registered = {"ArK株式会社": {"login_id": "ark", "co": "1", "upload_url": "u"}}
        book = FakeBook("✅完了 → 出力_X", plan=[HEAD, ["2026/10/30", "ArK株式会社", "8梱包", "FALSE", "通勤", "", "", "10"]])
        code, _, _, u, _ = self.run_schedule(book)
        self.assertEqual(code, 0)
        self.assertEqual(u.call_args[0][0].company, "ArK株式会社")

    def test_gas_stopped_before_reaching_row(self):
        book = FakeBook("", plan=[HEAD, DORM])
        book.overall = "⏹ 停止中(エラーのため停止。もう一度「③」を実行してください) (14:04:24時点)"
        code, _, c, _, _ = self.run_schedule(book)
        self.assertEqual(code, 2)
        c.assert_not_called()
        self.assertIn("GAS がエラーで止まりました", book.results[2])

    def test_other_pending_rows_stop_generation(self):
        # 入寮用の実行設定に、人が入れた未実行の予約行が残っているときは生成しない
        book = FakeBook("✅完了 → 出力_X", plan=[HEAD, DORM], pending=[4, 5, 6, 13])
        code, gas, c, _, _ = self.run_schedule(book)
        self.assertEqual(code, 2)
        self.assertEqual(book.appended, [])
        gas.return_value.run.assert_not_called()
        self.assertIn("4〜6、13行目", book.results[2])

    def test_missing_dorm_url_stops_before_anything(self):
        book = FakeBook("", plan=[HEAD, DORM])
        with mock.patch.dict("os.environ", {"QMATE_GAS_TOKEN_DORM": ""}):
            self.assertEqual(self.run_schedule(book)[0], 1)
        self.assertEqual(book.appended, [])


if __name__ == "__main__":
    unittest.main()
