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
