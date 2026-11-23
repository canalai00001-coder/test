"""掲載状況変更（求人メモで指定した原稿のステータスを変える）を確かめる。Q-mate には接続しない。"""
import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from qmate_agent import __main__ as main
from qmate_agent import config, status_change, takedown
from qmate_agent import schedule as sc

HEADER = ["UID", "更新種別|必須", "ステータス|必須", "職種名|必須", "メモ"]


def export_file(rows) -> Path:
    path = Path(tempfile.mkdtemp()) / "export.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    return path


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


class TestChunks(unittest.TestCase):
    def test_only_listed_memos_and_full_rows(self):
        src = export_file([["u1", "", "終了", "職種1", "22-261112-A-株式会社土/K"],
                           ["u2", "", "終了", "職種2", "22-261112-B-株式会社土/K"],
                           ["u3", "", "公開", "職種3", "22-261112-C-株式会社土/K"],   # すでに公開
                           ["u4", "", "下書き", "職種4", "22-261112-D-株式会社土/K"]])
        match = status_change.memo_matcher(["-A-", "-C-", "-D-", "-Z-"])
        paths, total = takedown.make_chunks(src, Path(tempfile.mkdtemp()), "x", "更新", "公開",
                                            keep=match, skip_status="公開")
        rows = read(paths[0])
        self.assertEqual(rows[1:], [["u1", "更新", "公開", "職種1", "22-261112-A-株式会社土/K"],
                                    ["u4", "更新", "公開", "職種4", "22-261112-D-株式会社土/K"]])
        self.assertEqual(total, 2)
        self.assertEqual(match.found, {"-A-", "-C-", "-D-"})  # -Z- は見つからない

    def test_merge_memos(self):
        self.assertEqual(status_change.merge_memos(["a\nb", "b、c", ""]), ["a", "b", "c"])

    def test_bad_status_refused_before_login(self):
        with self.assertRaisesRegex(RuntimeError, "変更後ステータス"):
            status_change.run("A社", ["m"], "掲載", {"csv": {}}, Path(tempfile.mkdtemp()))
        with self.assertRaisesRegex(RuntimeError, "求人メモが空欄"):
            status_change.run("A社", [], "公開", {"csv": {}}, Path(tempfile.mkdtemp()))


class TestNotFound(unittest.TestCase):
    def test_no_memo_found_is_an_error(self):
        from qmate_agent import uploader
        src = export_file([])

        class Up:
            def __init__(self, *a, **k):
                pass

            def export_template(self, status, out_path, memo="", log=None):
                return src
        with mock.patch("qmate_agent.accounts.qmate_config", return_value={}),                 mock.patch.object(uploader, "QmateUploader", Up):
            with self.assertRaisesRegex(RuntimeError, "1件もありません"):
                status_change.run("A社", ["m1"], "公開", {"csv": {}}, Path(tempfile.mkdtemp()), log=lambda *a: None)


class TestPlan(unittest.TestCase):
    def test_read(self):
        table = [["実行日", "会社", "求人メモ\n(複数は改行か「、」)", "対象ステータス\n(空欄=全て)", "変更後ステータス", "実行結果"],
                 [46349, "株式会社土", "m1\nm2", "", "公開", ""],
                 ["", "", "", "", "", ""],
                 ["2026/11/24", "ArK株式会社", "m3", "終了", "公開", ""]]
        rows = sc.read_status_plan(table, date(2026, 11, 23))
        self.assertEqual([(r.row, r.company, r.memos, r.status, r.to_status) for r in rows],
                         [(2, "株式会社土", "m1\nm2", "", "公開"), (4, "ArK株式会社", "m3", "終了", "公開")])
        self.assertEqual(rows[0].run_date, date(2026, 11, 23))
        self.assertEqual(sc.read_status_plan([["実行日", "会社"]], date(2026, 11, 23)), [])


class TestRunRows(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp()))
        p.start()
        self.addCleanup(p.stop)

    def test_same_company_rows_are_merged(self):
        def row(n, company, memos, to="公開", status=""):
            return sc.StatusRow(n, date(2026, 11, 23), company, memos, status, to)
        rows = [row(2, "A社", "m1"), row(3, "A社", "m2\nm1"), row(4, "B社", "m3"), row(5, "A社", "m4", to="終了")]
        calls = []

        def fake(company, memos, to, settings, out, **kw):
            calls.append((company, memos, to))
            return {"count": len(memos), "missing": [], "memos": len(memos)}
        written = []
        book = mock.Mock()
        book.write_plan_result.side_effect = lambda r, t, sheet=None: written.append((r, t))
        args = SimpleNamespace(headed=False, dry_run=False, parallel=None)
        with mock.patch.object(status_change, "run", fake), mock.patch("builtins.print"):
            failed = main._run_status_rows(rows, {"takedown": {"parallel": 4}}, args, book, "掲載状況変更")
        self.assertEqual(failed, 0)
        self.assertEqual(sorted(calls), [("A社", ["m1", "m2"], "公開"), ("A社", ["m4"], "終了"), ("B社", ["m3"], "公開")])
        self.assertEqual(sorted(r for r, _ in written), [2, 3, 4, 5])
        self.assertEqual(len(main._state("schedule.json")), 4)


class TestMarkDone(unittest.TestCase):
    def test_keeps_entries_written_by_another_run(self):
        with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())):
            mine = {}
            main._save_state("schedule.json", {"other": {"finished_at": "x"}})  # 別の実行が書いた
            main._mark_done(mine, ["k1"], {"count": 1})
            self.assertEqual(set(main._state("schedule.json")), {"other", "k1"})


if __name__ == "__main__":
    unittest.main()
