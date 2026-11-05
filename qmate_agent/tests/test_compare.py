"""GAS とツールの原稿の見比べを確かめる。"""
import unittest

from qmate_agent.checks import Manuscript
from qmate_agent.compare import compare

H = ["UID", "掲載企業名|必須", "メモ", "キーワードリスト（複数選択可）", "仕事内容|必須", "採用担当者名"]


def ms(rows):
    return Manuscript("x", [H] + rows)


class TestCompare(unittest.TestCase):
    def test_finds_structural_differences(self):
        gas = ms([["", "非公開", "22-261105-1-1-1-350001", "製造,寮", "A", "採用担当"],
                  ["", "非公開", "22-261105-1-1-1-351234", "製造,寮", "B", "採用担当"]])
        tool = ms([["", "非公開", "22-261105-1-1-1-359999", "製造", "C", ""],
                   ["", "非公開", "22-261105-1-1-1-350500", "製造", "A", ""]])
        lines, diff = compare(gas, tool)
        text = "\n".join(lines)
        self.assertEqual(diff, 2)
        self.assertIn("同じ（固定）　掲載企業名|必須", text)
        self.assertIn("✖ 固定の値が違う　キーワードリスト（複数選択可）", text)
        self.assertIn("✖ 片方だけ空欄　採用担当者名", text)
        self.assertIn("どちらも毎回変わる　メモ（同じ値 0種類／形が同じ 1種類）", text)
        self.assertNotIn("UID", text)

    def test_same_structure(self):
        a = ms([["", "非公開", "m1", "k", "A", "採用担当"], ["", "非公開", "m2", "k", "B", "採用担当"]])
        b = ms([["", "非公開", "m3", "k", "B", "採用担当"], ["", "非公開", "m4", "k", "A", "採用担当"]])
        self.assertEqual(compare(a, b)[1], 0)


if __name__ == "__main__":
    unittest.main()


class TestCompareCommand(unittest.TestCase):
    def test_reservation_is_taken_from_config_sheet(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest import mock

        from qmate_agent import __main__ as cli, config, generator
        from qmate_agent.qmate_headers import QMATE_HEADERS

        config_rows = [["タイトル"], ["見出し"], ["注記"],
                       ["予定2_1408-1", 46328, "通勤", "正社員（人材紹介）", "1クルマ", "AspiRove株式会社", 50, "登録", "下書き",
                        "", "35万", "夜勤あり", "", "タイトル2(施策)", "遠方からの応募可能", "",
                        "✅完了(2026-11-02 14:09) 50件 → 出力_G予定2_1408_AspiRove株式会社_1クルマ_20261102"]]
        row = {h: "" for h in QMATE_HEADERS} | {"掲載企業名|必須": "非公開"}
        gas = Manuscript("出力_G予定2_1408", [QMATE_HEADERS] + [[row[h] for h in QMATE_HEADERS]] * 2)
        book = SimpleNamespace(config_table=lambda: config_rows, manuscript=lambda name: gas)
        seen = {}

        def fake_run(settings, target, req, **kw):
            seen["req"], seen["kw"] = req, kw
            return generator.Result([dict(row), dict(row)], {}, [])
        with mock.patch.object(cli, "_spreadsheet", return_value=book), mock.patch.object(generator, "run", fake_run), \
                mock.patch.object(config, "OUTPUT_DIR", Path(tempfile.mkdtemp())), mock.patch("builtins.print"):
            code = cli.cmd_compare(SimpleNamespace(gas_sheet="出力_G予定2_1408_AspiRove株式会社_1クルマ_20261102",
                                                   commute="通勤"))
        self.assertEqual(code, 0)
        r = seen["req"]
        self.assertEqual((r.category, r.count, r.salary_pattern, r.night, r.title_measure, r.box_word, r.status),
                         ("1クルマ", 2, "35万", "夜勤あり", "タイトル2(施策)", "遠方からの応募可能", "下書き"))
        self.assertEqual(str(r.created), "2026-11-02")
        self.assertEqual(seen["kw"], {"record_usage": False, "ignore_cooldown": True, "dorm": False})
