"""前回分の取り下げ（取り出した CSV の書き換えと分割）を確かめる。Q-mate には接続しない。"""
import csv
import tempfile
import unittest
from pathlib import Path

from qmate_agent import takedown

from datetime import date

HEADER = ["UID", "更新種別|必須", "ステータス|必須", "職種名|必須", "仕事内容|必須", "メモ"]


def export_file(rows: int, no_uid_at=None) -> Path:
    path = Path(tempfile.mkdtemp()) / "export.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i in range(rows):
            memo = f"22-2610{20 + i % 5:02d}-2-2-7A-1495-1868-38-兵庫県芦屋市-AspiRove株式会社/G"
            w.writerow(["" if i == no_uid_at else f"uid{i}", "", "公開", f"職種{i}", "改行を\n含む仕事内容", memo])
    return path


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


class TestChunks(unittest.TestCase):
    def test_split_and_rewrite(self):
        src = export_file(25, no_uid_at=3)
        out = Path(tempfile.mkdtemp())
        paths, total = takedown.make_chunks(src, out, "取り下げ_A社", "削除", "終了", chunk_rows=10)
        self.assertEqual(total, 24)  # UID のない行は飛ばす
        self.assertEqual([p.name for p in paths], ["取り下げ_A社_1.csv", "取り下げ_A社_2.csv", "取り下げ_A社_3.csv"])
        sizes = [len(read(p)) - 1 for p in paths]
        self.assertEqual(sizes, [10, 10, 4])
        for p in paths:
            rows = read(p)
            self.assertEqual(rows[0], HEADER)
            self.assertTrue(all(r[1] == "削除" and r[2] == "終了" for r in rows[1:]))
        self.assertEqual(read(paths[0])[1][4], "改行を\n含む仕事内容")
        self.assertNotIn("uid3", [r[0] for p in paths for r in read(p)])

    def test_exact_multiple_has_no_empty_file(self):
        paths, total = takedown.make_chunks(export_file(20), Path(tempfile.mkdtemp()), "x", "削除", "終了", chunk_rows=10)
        self.assertEqual((len(paths), total), (2, 20))

    def test_empty_export(self):
        paths, total = takedown.make_chunks(export_file(0), Path(tempfile.mkdtemp()), "x", "削除", "終了")
        self.assertEqual((paths, total), ([], 0))

    def test_period_filter(self):
        # メモの作成日は 10/20〜10/24 が5件ずつ。10/21〜10/22 だけを取り下げる
        keep = takedown.row_filter(date(2026, 10, 21), date(2026, 10, 22))
        paths, total = takedown.make_chunks(export_file(25), Path(tempfile.mkdtemp()), "x", "削除", "終了", keep=keep)
        self.assertEqual(total, 10)
        self.assertTrue(all(r[5].split("-")[1] in ("261021", "261022") for r in read(paths[0])[1:]))

    def test_memo_date_and_query(self):
        self.assertEqual(takedown.memo_date("22-261104-1-1-7A-x"), date(2026, 11, 4))
        self.assertIsNone(takedown.memo_date("手書きのメモ"))
        self.assertEqual(takedown.memo_filter(date(2026, 11, 4), date(2026, 11, 4)), "-261104-")
        self.assertEqual(takedown.memo_filter(date(2026, 11, 1), date(2026, 11, 4)), "")
        self.assertEqual(takedown.memo_filter(None, None, "-2-2-7"), "-2-2-7")
        # 期間を指定したとき、作成日が読めないメモの原稿は取り下げない
        self.assertFalse(takedown.row_filter(date(2026, 11, 1), None)("手書きのメモ"))
        self.assertTrue(takedown.row_filter(None, None, "-2-2-7")("22-261104-2-2-7A"))

    def test_period_is_exported_by_month(self):
        # 期間を指定したら、会社の全原稿ではなく月ごとに Q-mate 側で絞って書き出す
        self.assertEqual(takedown.memo_filters(date(2026, 10, 29), date(2026, 11, 11)), ["-2610", "-2611"])
        self.assertEqual(takedown.memo_filters(date(2026, 12, 20), date(2027, 1, 5)), ["-2612", "-2701"])
        self.assertEqual(takedown.memo_filters(date(2026, 11, 4), date(2026, 11, 4)), ["-261104-"])
        self.assertEqual(takedown.memo_filters(None, None), [""])
        self.assertEqual(takedown.memo_filters(date(2026, 1, 1), date(2026, 12, 31)), [""])  # 長すぎる期間は分けない
        self.assertEqual(takedown.memo_filters(date(2026, 10, 1), date(2026, 11, 1), "-2-2-7"), ["-2-2-7"])

    def test_several_exports_are_merged_without_duplicates(self):
        a, b = export_file(10), export_file(10)  # 同じ UID が2つのファイルにある
        paths, total = takedown.make_chunks([a, b], Path(tempfile.mkdtemp()), "x", "削除", "終了")
        self.assertEqual(total, 10)
        self.assertEqual(len(read(paths[0])), 11)

    def test_other_company_refused(self):
        settings = {"takedown": {}, "qmate": {"company": "AspiRove株式会社"}, "csv": {}}
        with self.assertRaises(RuntimeError):
            takedown.run("ArK株式会社", settings, Path(tempfile.mkdtemp()))


if __name__ == "__main__":
    unittest.main()
