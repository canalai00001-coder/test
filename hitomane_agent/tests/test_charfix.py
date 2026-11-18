"""CSV（Shift_JIS）で書けない記号の置き換え（charfix.py）。"""
import unittest

from hitomane_agent import charfix


class TestCharfix(unittest.TestCase):
    def test_all_replacements_are_writable(self):
        for k, v in charfix.REPLACE.items():
            v.encode("cp932")
            with self.assertRaises(UnicodeEncodeError):
                k.encode("cp932")

    def test_fix(self):
        counts = {}
        self.assertEqual(charfix.fix("▶勤務時間\n✓未経験OK ✔寮あり ☑\uFE0E日払い🇮🇹", counts), "■勤務時間\n○未経験OK ○寮あり ○日払い")
        self.assertEqual(counts["✓→○"], 1)
        self.assertEqual(counts["U+FE0E→（消す）"], 1)
        self.assertEqual(charfix.fix("abc"), "abc")
        self.assertEqual(charfix.fix(""), "")

    def test_unknown_is_kept(self):
        self.assertEqual(charfix.fix("😀"), "😀")  # 表にないものは残して、チェックで知らせる

    def test_rows(self):
        rows, counts = charfix.fix_rows([["▷a", "x"], ["▷b", "♦"]])
        self.assertEqual(rows, [["□a", "x"], ["□b", "◆"]])
        self.assertEqual(charfix.summary(counts), "▷→□ 2か所、♦→◆ 1か所")


if __name__ == "__main__":
    unittest.main()
