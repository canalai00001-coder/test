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


class TestUsePrepared(unittest.TestCase):
    """確認（ドライラン）で取り出したファイルを、取り出し直さずに使って取り下げる。"""

    def setUp(self):
        from unittest import mock
        from qmate_agent import config
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(config, "STATE_DIR", self.tmp / "state")
        p.start()
        self.addCleanup(p.stop)
        self.files = []
        d = self.tmp / "取り下げ_A社_20261113_1000"
        d.mkdir()
        for i in range(3):
            f = d / f"取り下げ_A社_20261113_1000_{i + 1}.csv"
            f.write_text("x", encoding="utf-8")
            self.files.append(str(f))
        self.name = takedown.save_prepared({"company": "A社", "count": 25000, "files": self.files, "span": "作成日：全期間",
                                            "memo": "", "at": "2026-11-13T10:00:00"}, "公開")

    def use(self, results, today=date(2026, 11, 13)):
        from unittest import mock
        from types import SimpleNamespace
        sent = []

        class Up:
            def __init__(self, *a, **k):
                pass

            def upload(self, path, label):
                sent.append(path.name)
                return SimpleNamespace(ok=results.pop(0), message="エラー")
        settings = {"takedown": {}, "qmate": {}}
        with mock.patch("qmate_agent.accounts.qmate_config", return_value={}), \
                mock.patch("qmate_agent.uploader.QmateUploader", Up):
            return takedown.use_prepared(self.name, settings, log=lambda *a: None, today=today), sent

    def test_listed_today_only(self):
        self.assertEqual([r["name"] for r in takedown.prepared_list(date(2026, 11, 13))], [self.name])
        self.assertEqual(takedown.prepared_list(date(2026, 11, 14)), [])
        with self.assertRaisesRegex(RuntimeError, "取り出した日を過ぎて"):
            self.use([True] * 3, today=date(2026, 11, 14))

    def test_uses_files_without_export_and_only_once(self):
        result, sent = self.use([True] * 3)
        self.assertEqual(len(sent), 3)
        self.assertEqual(result["count"], 25000)
        self.assertEqual(takedown.prepared_list(date(2026, 11, 13)), [])
        with self.assertRaisesRegex(RuntimeError, "取り下げ済み"):
            self.use([True])

    def test_resumes_after_failure(self):
        with self.assertRaisesRegex(RuntimeError, "残りのファイルから続けます"):
            self.use([True, False])
        result, sent = self.use([True, True])
        self.assertEqual(sent, [Path(f).name for f in self.files[1:]])  # 1本目は前回取り込み済み


class TestRunReusesDryRun(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        from datetime import datetime
        from qmate_agent import config
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(config, "STATE_DIR", self.tmp / "state")
        p.start()
        self.addCleanup(p.stop)
        f = self.tmp / "取り下げ_A社_x" / "1.csv"
        f.parent.mkdir()
        f.write_text("x", encoding="utf-8")
        cond = takedown.conditions("A社", date(2026, 10, 29), date(2026, 11, 11), "", "公開")
        takedown.save_prepared({"company": "A社", "count": 5, "files": [str(f)], "span": "s", "memo": "",
                                "at": datetime.now().isoformat(timespec="seconds")}, "公開", cond)

    def run_td(self, **kw):
        from unittest import mock
        settings = {"takedown": {"export_status": "公開", "update_type": "削除", "status": "終了"}, "qmate": {}, "csv": {}}
        args = dict(date_from=date(2026, 10, 29), date_to=date(2026, 11, 11), export_status="公開")
        args.update(kw)
        with mock.patch.object(takedown, "use_prepared", return_value={"count": 5}) as use, \
                mock.patch("qmate_agent.accounts.qmate_config", side_effect=RuntimeError("取り出しに進んだ")):
            try:
                takedown.run("A社", settings, self.tmp, log=lambda *a: None, **args)
            except RuntimeError as e:
                return use, str(e)
        return use, ""

    def test_same_conditions_skip_export(self):
        use, err = self.run_td()
        use.assert_called_once()
        self.assertEqual(err, "")

    def test_other_conditions_export_again(self):
        use, err = self.run_td(date_to=date(2026, 11, 12))
        use.assert_not_called()
        self.assertEqual(err, "取り出しに進んだ")
