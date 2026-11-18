"""入稿予定表（読み方・予約への変換・schedule コマンド・操作画面）。"""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

from hitomane_agent import __main__ as cli
from hitomane_agent import app as app_mod
from hitomane_agent import config, generated, generator as g, plan, workflow
from tests import gen_samples as s
from tests.test_workflow import FakeUploader

TODAY = date(2026, 11, 20)
H = plan.HEADERS
RES = [plan.header_name(h) for h in H].index("実行結果") + 1  # 実行結果の列（1始まり）


def prow(d="2026/11/20", company="canal benefits株式会社", category="5半導体", night="TRUE", count="2", prefix="",
         title="", image="製造", result="", **more):
    r = dict.fromkeys([plan.header_name(h) for h in H], "")
    r.update({"実行日": d, "会社": company, "職種": category, "夜勤有無": night, "原稿数": count, "募集番号の先頭": prefix,
              "職種名選択": title, "画像カテゴリー": image, "実行結果": result, **more})
    return [r[plan.header_name(h)] for h in H]


class FakeWs:
    def __init__(self, table):
        self.table = table
        self.cells = {}

    def get_all_values(self):
        return self.table

    def row_values(self, n):
        return self.table[n - 1]

    def update_cell(self, row, col, value):
        self.cells[(row, col)] = value


class FakeBook:
    def __init__(self, table):
        self.ws = FakeWs(table)

    def worksheet(self, name):
        assert name == plan.SHEET
        return self.ws


class TestRead(unittest.TestCase):
    def test_read(self):
        rows = plan.read_plan([H, prow(), prow(d="11/21", night="FALSE", count=""), prow(company="")], TODAY)
        self.assertEqual([(p.row, p.run_date, p.night, p.count) for p in rows],
                         [(2, TODAY, True, "2"), (3, date(2026, 11, 21), False, "")])
        p = rows[0]
        self.assertEqual((p.commute, p.employment, p.status, p.salary), ("通勤", "正社員", "掲載", "基本"))  # 空欄は決まった値

    def test_missing_headers(self):
        with self.assertRaisesRegex(RuntimeError, "「実行日」"):
            plan.read_plan([["会社", "職種"]], TODAY)

    def test_targets(self):
        rows = plan.read_plan([H, prow(prefix="CB1"), prow(title="グラスの検品", category="7軽め"),
                               prow(company="株式会社エイトビィ")], TODAY)
        with self.assertRaisesRegex(RuntimeError, "4行目：株式会社エイトビィ をツールで入稿するのは初めて"):
            plan.to_targets(rows, TODAY, {})
        ts = plan.to_targets(rows, TODAY, {"株式会社エイトビィ": "eightbee500"})
        self.assertEqual([(t.group_id, t.entry_prefix, t.paired_title, t.night_shift, t.format) for t in ts], [
            ("予定2", "CB1", "", "夜勤あり", "新FMT"), ("予定3", "", "7軽め｜グラスの検品", "夜勤あり", "新FMT"),
            ("予定4", "eightbee500", "", "夜勤あり", "新FMT")])
        self.assertEqual(ts[0].creation_date, "2026/11/20")

    def test_header_names(self):
        self.assertEqual(plan.header_name("職種名指定(空欄=ランダム)"), "職種名指定")
        self.assertEqual(plan.header_name("原稿数\n(空欄=勤務地の数)"), "原稿数")
        # 担当者が足した見出しの形（2026-11-18 の入稿予定表）でも読める
        head = ["実行日", "会社", "職種", "夜勤有無", "フォーマット", "職種名指定(空欄=ランダム)", "分類(6重め/7軽めのみ)",
                "勤務地_都道府県", "勤務地_市区町村"]
        p = plan.read_plan([head, ["2026/11/20", "合同会社Y Gift", "7軽め", "TRUE", "旧FMT", "グラスの検品", "手のひら",
                                   "宮崎県", "日向市"]], TODAY)[0]
        self.assertEqual((p.method, p.fmt, p.title_spec, p.bunrui, p.pref, p.city),
                         ("通常", "旧FMT", "グラスの検品", "手のひら", "宮崎県", "日向市"))
        self.assertIn("施策", p.problem())  # 作り方が通常のままでは作らない

    def test_problems(self):
        read = lambda **k: plan.read_plan([H, prow(**k)], TODAY)[0]
        self.assertIsNone(read().problem())
        self.assertIn("新FMT だけ", read(フォーマット="旧FMT").problem())
        self.assertIn("「勤務地_都道府県」は作り方が「施策」", read(勤務地_都道府県="宮崎県").problem())
        self.assertIsNone(read(作り方="施策", フォーマット="旧FMT", 勤務地_都道府県="宮崎県").problem())
        self.assertIn("職種名指定", read(作り方="施策", title="グラスの検品").problem())
        self.assertIn("「通常」か「施策」", read(作り方="特別").problem())
        self.assertIn("「新FMT」か「旧FMT」", read(作り方="施策", フォーマット="FMT").problem())
        # 前からの行（通常・新FMT）は、実行済みの印が変わらない
        self.assertEqual(read().key.count("|"), 13)
        self.assertNotEqual(read().key, read(作り方="施策").key)

    def test_shisaku_targets(self):
        rows = plan.read_plan([H, prow(作り方="施策", フォーマット="旧FMT", 職種名指定="グラスの検品", 分類="手のひら",
                                       勤務地_都道府県="宮崎県", 勤務地_市区町村="日向市", prefix="Y1")], TODAY)
        t = plan.to_targets(rows, TODAY, {})[0]
        self.assertEqual((t.format, t.title_spec, t.bunrui, t.pref, t.city, t.paired_title),
                         ("旧FMT", "グラスの検品", "手のひら", "宮崎県", "日向市", ""))

    def test_next_number(self):
        self.assertEqual(plan.next_number("canalbenefits000199"), "canalbenefits000200")


class TestSchedule(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        for name, value in (("OUTPUT_DIR", d / "output"), ("STATE_DIR", d / "state")):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.book = FakeBook([H, prow(prefix="CB1"), prow(count="1"), prow(d="2026/11/21", prefix="X1")])
        info = {"login_id": "Minami", "password": "pw", "url": "http://x/m66w/", "company": "canal benefits株式会社",
                "code": "m66w"}
        patches = [mock.patch.object(cli, "_books", return_value=(None, self.book)),
                   mock.patch.object(g, "load_base", return_value=(s.grids(), s.usage())),
                   mock.patch("hitomane_agent.uploader.HitomaneUploader", FakeUploader),
                   mock.patch("hitomane_agent.accounts.companies",
                              return_value=[{"company": "canal benefits株式会社", "code": "m66w", "url": "u"}]),
                   mock.patch("hitomane_agent.accounts.login_info", lambda s, book=None, company=None: info)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        FakeUploader.calls, FakeUploader.ok, FakeUploader.total_value = [], True, 100
        FakeUploader.branches, FakeUploader.infos = [{"code": "B001", "name": "CB株式会社"}], []

    def cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["schedule", "--date", "2026-11-20", *argv])
        return code, buf.getvalue()

    def test_dry_run_makes_and_checks_only(self):
        code, out = self.cli("--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("2件 をテスト（作ってチェックするだけ）", out)
        self.assertEqual(FakeUploader.calls, [])
        self.assertEqual(self.book.ws.cells, {})  # テストは予定表に書かない
        names = [x["name"] for x in generated.listing()]
        self.assertEqual(sorted(names), ["ツール_新_G予定2_canal benefits株式会社_5半導体_20261120",
                                         "ツール_新_G予定3_canal benefits株式会社_5半導体_20261120"])

    def test_run_uploads_writes_result_and_remembers(self):
        code, out = self.cli("--yes")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(FakeUploader.calls), 2)
        self.assertEqual(sorted(self.book.ws.cells), [(2, RES), (3, RES)])  # 実行結果の列
        self.assertTrue(self.book.ws.cells[(2, RES)].startswith("入稿済み"))
        self.assertEqual(plan.entry_numbers(), {"canal benefits株式会社": "CB4"})  # 2件＋1件のあと
        self.assertEqual(len(plan.done()), 2)
        # もう一度動かしても、実行済みの行はやらない
        code, out = self.cli("--yes")
        self.assertIn("実行済みです", out)
        self.assertEqual(len(FakeUploader.calls), 2)
        # 次に作るときは、入稿した職種名を避ける（このパソコンの記録）
        u = plan.merge_usage(s.usage())
        self.assertTrue(any(r[0] == "canal benefits株式会社" for r in u.title_rows))

    def test_over_limit_is_not_uploaded(self):
        FakeUploader.total_value = 49999
        code, out = self.cli("--yes", "--row", "2")
        self.assertEqual(code, 2)
        self.assertIn("上限 50,000件を超えます", out)
        self.assertEqual(FakeUploader.calls, [])
        self.assertTrue(self.book.ws.cells[(2, RES)].startswith("❌"))

    def test_ng_is_not_uploaded(self):
        self.book.ws.table[1] = prow(prefix="CB1", category="9検査")  # 職種名の無いカテゴリー
        code, out = self.cli("--yes", "--row", "2")
        self.assertEqual(code, 2)
        self.assertIn("作れませんでした", out)
        self.assertEqual(FakeUploader.calls, [])

    def test_shisaku_rows(self):
        shisaku_patches = (mock.patch.object(cli, "_shisaku_books", return_value=(None, None, "")),
                           mock.patch("hitomane_agent.shisaku.load_base", side_effect=lambda book: s.shisaku_base()))
        for p in shisaku_patches:
            p.start()
            self.addCleanup(p.stop)
        # 旧FMT は作ってチェックするまで（入稿しない）
        self.book.ws.table[1] = prow(prefix="CB1", 作り方="施策", フォーマット="旧FMT", 勤務地_都道府県="東京都")
        code, out = self.cli("--yes", "--row", "2")
        self.assertEqual(code, 2, out)
        self.assertIn("ツールからの旧FMT の取り込みはまだできない", out)
        self.assertEqual(FakeUploader.calls, [])
        self.assertTrue(self.book.ws.cells[(2, RES)].startswith("❌旧FMT の原稿を作ってチェックしました"))
        # 新FMT は入稿する。勤務地×職種名をこのパソコンの記録に残す
        self.book.ws.table[1] = prow(prefix="CB1", 作り方="施策", 勤務地_都道府県="東京都")
        code, out = self.cli("--yes", "--row", "2")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(FakeUploader.calls), 1)
        self.assertIn("施策・新FMT・東京都", out)
        base = plan.merge_shisaku_usage(s.shisaku_base())
        # 原稿数 2 を東京都の勤務地（葛飾区だけ）に作ったので、職種名は2つとも使った
        self.assertEqual(base.loc_used["canal benefits株式会社||東京都||葛飾区"], {"半導体の製造A", "半導体の製造B"})

    def test_problem_row_is_not_made(self):
        self.book.ws.table[1] = prow(prefix="CB1", 勤務地_都道府県="東京都")  # 作り方が通常のまま
        code, out = self.cli("--yes", "--row", "2")
        self.assertEqual(code, 2)
        self.assertIn("作り方が「施策」のときだけ", out)
        self.assertEqual(FakeUploader.calls, [])

    def test_unknown_company(self):
        self.book.ws.table[1] = prow(prefix="CB1", company="株式会社エイトビィ")
        code, out = self.cli("--yes", "--row", "2")
        self.assertEqual(code, 1)
        self.assertIn("入稿先が分かりません", out)

    def test_nothing_today(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["schedule", "--date", "2026-12-01"])
        self.assertEqual(code, 0)
        self.assertIn("2026/12/01 に実行する行がありません", buf.getvalue())


class TestScreen(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        for name, value in (("OUTPUT_DIR", d / "output"), ("STATE_DIR", d / "state")):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.app = app_mod.App(book=None)

    def test_schedule_list(self):
        today = f"{date.today():%Y/%m/%d}"
        with mock.patch.object(app_mod.App, "_schedule_table", return_value=[H, prow(d=today), prow(d="2020/01/01")]):
            d = self.app.schedule()
        self.assertTrue(d["exists"])
        self.assertEqual([(r["row"], r["today"], r["done"]) for r in d["rows"]], [(2, True, False), (3, False, False)])
        with mock.patch.object(app_mod.App, "_schedule_table", return_value=None):
            self.assertFalse(self.app.schedule()["exists"])

    def test_schedule_args(self):
        self.assertEqual(self.app.schedule_args({})[1], ["schedule", "--yes"])
        self.assertEqual(self.app.schedule_args({"rows": [5], "dry_run": True})[1],
                         ["schedule", "--yes", "--row", "5", "--dry-run"])


if __name__ == "__main__":
    unittest.main()
