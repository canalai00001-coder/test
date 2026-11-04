"""前回分の取り下げ（取り出した CSV の書き換えと分割）を確かめる。Q-mate には接続しない。"""
import csv
import tempfile
import unittest
from pathlib import Path

from qmate_agent import takedown

HEADER = ["UID", "更新種別|必須", "ステータス|必須", "職種名|必須", "仕事内容|必須"]


def export_file(rows: int, no_uid_at=None) -> Path:
    path = Path(tempfile.mkdtemp()) / "export.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i in range(rows):
            w.writerow(["" if i == no_uid_at else f"uid{i}", "", "公開", f"職種{i}", "改行を\n含む仕事内容"])
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

    def test_other_company_refused(self):
        settings = {"takedown": {}, "qmate": {"company": "AspiRove株式会社"}, "csv": {}}
        with self.assertRaises(RuntimeError):
            takedown.run("ArK株式会社", settings, Path(tempfile.mkdtemp()))


if __name__ == "__main__":
    unittest.main()
