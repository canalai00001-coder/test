"""取り込み用の CSV。"""
import unittest

from hitomane_agent.checks import Manuscript
from hitomane_agent.csv_export import read_csv, split_rows, to_csv_bytes
from tests.samples import row, table


class TestCsvExport(unittest.TestCase):
    def test_format_matches_exported_csv(self):
        # 取り出した CSV と同じ形：cp932・BOM なし・CRLF・セルの中の改行も CRLF・必要なときだけ "" で囲む・空欄は ""
        ms = Manuscript("x", table(row(**{"PR": "1行目\n2行目", "募集職種": 'カンマ,と"引用符"'})))
        b = to_csv_bytes(ms)
        self.assertFalse(b.startswith(b"\xef\xbb\xbf"))
        t = b.decode("cp932")
        self.assertTrue(t.startswith("募集番号,開始日,終了日,ステータス,"))
        self.assertTrue(t.endswith("\r\n"))
        self.assertIn('"1行目\r\n2行目"', t)
        self.assertIn('"カンマ,と""引用符"""', t)
        self.assertIn(",test0001,", "," + t.split("\r\n")[1])  # 囲まなくてよいセルは囲まない
        self.assertNotIn("\n", t.replace("\r\n", ""))
        head, data = t.split("\r\n", 1)
        self.assertNotIn('""', head)  # 見出しは囲まない
        self.assertIn(',"",', data)  # データ行の空欄は "" と書く（取り出した CSV と同じ）

    def test_round_trip(self):
        ms = Manuscript("x", table(row(**{"PR": "1行目\r\n2行目"})))
        b = to_csv_bytes(ms)
        back = read_csv(b, "x")
        self.assertEqual(back.headers, ms.headers)
        self.assertEqual(to_csv_bytes(back), b)

    def test_reads_utf8_too(self):
        ms = Manuscript("x", table(row()))
        b = to_csv_bytes(ms).decode("cp932").encode("utf-8-sig")
        self.assertEqual(read_csv(b, "x").rows[0]["募集番号"], "test0001")

    def test_cannot_write_emoji(self):
        ms = Manuscript("x", table(row(**{"PR": "😀"})))
        with self.assertRaises(UnicodeEncodeError):
            to_csv_bytes(ms)

    def test_split_rows(self):
        rows = [row(**{"募集番号": f"t{i}"}) for i in range(5)]
        ms = Manuscript("x", table(*rows))
        parts = split_rows(ms, 2)
        self.assertEqual([len(p.rows) for p in parts], [2, 2, 1])
        self.assertEqual(parts[2].rows[0]["募集番号"], "t4")
        self.assertEqual([p.name for p in parts], ["x_1", "x_2", "x_3"])
        self.assertEqual([p.name for p in split_rows(ms, 10)], ["x"])


if __name__ == "__main__":
    unittest.main()
