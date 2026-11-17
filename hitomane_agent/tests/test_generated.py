"""ツールで作った原稿の保存・チェック・比較・入稿（コマンドと操作画面）。"""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

from hitomane_agent import __main__ as cli
from hitomane_agent import app as app_mod
from hitomane_agent import compare, config, generated, generator as g, workflow
from hitomane_agent.checks import Manuscript, check_sheet
from tests import gen_samples as s
from tests.samples import row, table
from tests.test_workflow import FakeUploader, fake_login_info

NOW = datetime(2026, 11, 17, 12, 0)
PLAN = s.CONFIG_HEAD + [s.plan_row("1-1", count="2", prefix="CB1"), s.plan_row("1-2", count="2"),
                        s.plan_row("2-1", count="1", fmt="旧FMT")]


class Base(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        for name, value in (("OUTPUT_DIR", d / "output"), ("STATE_DIR", d / "state")):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)

    def make(self, rows=PLAN, only=None):
        res = g.run(g.build_bank(s.grids()), s.usage(), g.read_targets(rows), only_groups=only, seed=3, now=NOW,
                    today=NOW.date())
        return [generated.save(r, {"source": "テスト"}) for r in res if r.rows]


class TestGenerated(Base):
    def test_save_and_load(self):
        name = self.make()[0]
        self.assertEqual(name, "ツール_新_G1_canal benefits株式会社_5半導体_20261120")
        ms = generated.load(name)
        self.assertEqual((len(ms.rows), ms.segments), (4, [0, 2]))
        m = generated.meta(name)
        self.assertEqual((m["group"], m["sheet_rows"], m["rows"]), ("1", [4, 5], 4))
        self.assertEqual(generated.listing()[0]["name"], name)
        self.assertEqual(generated.gas_name_for(name), "ヒトマネ出力_新_G1_canal benefits株式会社_5半導体_20261120")

    def test_bad_names_are_refused(self):
        for bad in ("../x", "ツール_../x", "x", "ツール_a/b"):
            with self.assertRaises((ValueError, FileNotFoundError)):
                generated.load(bad)

    def test_duplicate_place_is_counted_per_reservation_row(self):
        # 予約行が違えば同じ勤務地でよい（GAS の⑤検品と同じ数え方）
        rows = [row(**{"募集番号": f"n{i}", "勤務地_市区町村": "池田市"}) for i in range(3)]
        _, res = check_sheet(Manuscript("x", table(*rows), segments=[0, 1, 2]), config.load("rules.json"))
        self.assertEqual([i for r in res for i in r if i.column == "勤務地_市区町村"], [])
        _, res = check_sheet(Manuscript("x", table(*rows), segments=[0, 2]), config.load("rules.json"))
        dup = [i.message for r in res for i in r if i.column == "勤務地_市区町村"]
        self.assertEqual(len(dup), 2)
        self.assertIn("同じ予約行（1つ目）の中で重複", dup[0])

    def test_branch_name_must_match(self):
        ms = Manuscript("x", table(row(**{"拠点コード": "B001", "拠点": "株式会社エイトビィ"})))
        p = workflow.branch_problem(ms, [{"code": "B001", "name": "CB株式会社"}], "canal benefits株式会社")
        self.assertIn("拠点と拠点名が違います：B001 株式会社エイトビィ", p)
        ms = Manuscript("x", table(row(**{"拠点コード": "B001", "拠点": "CB株式会社"})))
        self.assertIsNone(workflow.branch_problem(ms, [{"code": "B001", "name": "CB株式会社"}]))


class TestCompare(unittest.TestCase):
    def test_compare(self):
        gas = Manuscript("g", table(row(**{"募集番号": "a", "PR": "x"}), row(**{"募集番号": "b", "PR": "y"})))
        tool = Manuscript("t", table(row(**{"募集番号": "c", "PR": "z", "担当": "別の人"}),
                                     row(**{"募集番号": "d", "PR": "z", "担当": "別の人"})))
        lines, diff = compare.compare(gas, tool)
        text = "\n".join(lines)
        self.assertIn("✖ 固定の値が違う　担当", text)
        self.assertIn("✖ GAS は毎回変わる・ツールは固定　PR", text)
        self.assertIn("どちらも毎回変わる　募集番号", text)
        self.assertEqual(diff, 2)


class TestCommands(Base):
    def setUp(self):
        super().setUp()
        patches = [mock.patch.object(cli, "_books", return_value=(None, None)),
                   mock.patch.object(g, "load_base", return_value=(s.grids(), s.usage())),
                   mock.patch.object(g, "load_config", return_value=PLAN),
                   mock.patch("hitomane_agent.uploader.HitomaneUploader", FakeUploader),
                   mock.patch("hitomane_agent.accounts.login_info", fake_login_info)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        FakeUploader.calls, FakeUploader.ok, FakeUploader.total_value = [], True, 100
        FakeUploader.branches, FakeUploader.infos = [{"code": "B001", "name": "CB株式会社"}], []

    def cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(list(argv))
        return code, buf.getvalue()

    def test_plan(self):
        code, out = self.cli("plan")
        self.assertIn("グループ 1: canal benefits株式会社・5半導体・新FMT・2行（2+2）・GAS：未実行", out)

    def test_generate_then_upload(self):
        code, out = self.cli("generate", "--group", "1")
        self.assertIn("ツール_新_G1_canal benefits株式会社_5半導体_20261120", out)
        self.assertIn("原稿 4件、チェック OK", out)
        self.assertIn("使用履歴には書いていません", out)
        name = generated.listing()[0]["name"]
        code, out = self.cli("upload", "--generated", name, "--company", "m66w", "--yes")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(FakeUploader.calls), 1)
        ms = generated.load(name)
        self.assertIn(ms.rows[0]["募集番号"].encode("cp932"), FakeUploader.calls[0][0])

    def test_generate_needs_group(self):
        self.assertEqual(self.cli("generate")[0], 1)
        code, out = self.cli("generate", "--group", "9")
        self.assertIn("予約リストにないグループです：9", out)

    def test_generate_old_format_group(self):
        code, out = self.cli("generate", "--group", "2")
        self.assertIn("旧FMT", out)
        self.assertEqual(generated.listing(), [])


class TestScreen(Base):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(app_mod.App, "_plan_table", return_value=PLAN)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(app_mod.App, "_companies", return_value=[
            {"company": "canal benefits株式会社", "code": "m66w", "url": "u"}])
        p.start()
        self.addCleanup(p.stop)
        self.app = app_mod.App(book=None)

    def test_plan_and_generate_args(self):
        plan = self.app.plan()
        self.assertEqual([(x["group"], x["format"], x["rows"], x["counts"]) for x in plan],
                         [("1", "新FMT", [4, 5], ["2", "2"]), ("2", "旧FMT", [6], ["1"])])
        self.assertEqual(self.app.generate_args({"groups": ["1"]})[1], ["generate", "--group", "1"])
        with self.assertRaises(RuntimeError):
            self.app.generate_args({"groups": []})

    def test_generated_check_and_upload_args(self):
        name = self.make(only={"1"})[0]
        self.assertEqual(self.app.plan()[0]["made"], name)
        self.assertEqual(self.app.generated_list("m66w")[0]["status"], "")
        with self.assertRaises(RuntimeError):  # チェックの前は入稿しない
            self.app.upload_args({"name": name, "company": "m66w", "generated": True})
        self.assertEqual(self.app.check(name, gen=True)["status"], "OK")
        title, args = self.app.upload_args({"name": name, "company": "m66w", "generated": True})
        self.assertEqual(args, ["upload", "--generated", name, "--company", "m66w", "--yes"])
        r = self.app.prepare(name, "m66w", {"total": 1, "branches": [{"code": "B001", "name": "別の会社"}]}, gen=True)
        self.assertIn("拠点名が違います", r.get("problem", ""))


if __name__ == "__main__":
    unittest.main()
