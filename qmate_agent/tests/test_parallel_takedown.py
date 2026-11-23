"""取り下げ予定表の行を会社ごとに同時に動かすことを確かめる。Q-mate には接続しない。"""
import tempfile
import threading
import time
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from qmate_agent import __main__ as main
from qmate_agent import config, takedown


def row(n, company, keep_memo="", date_to=date(2026, 11, 2)):
    return SimpleNamespace(row=n, company=company, key=f"td-{n}", date_from=date(2026, 11, 1),
                           date_to=date_to, memo="", status="", keep_memo=keep_memo)


class TestParallelRows(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(config, "STATE_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def run_rows(self, rows, parallel=4, fail=()):
        self.calls = []
        running, peak, order, lock = set(), [0], [], threading.Lock()

        def fake(company, settings, headed, dry_run, log=print, **kw):
            self.calls.append((company, kw.get("keep_memo")))
            with lock:
                running.add(company)
                peak[0] = max(peak[0], len(running))
                order.append(company)
            time.sleep(0.3)
            with lock:
                running.discard(company)
            if company in fail:
                return RuntimeError("だめでした")
            main._record_takedown({"company": company, "count": 1})
            return {"count": 1, "span": "s"}

        written = []
        book = mock.Mock()
        book.write_plan_result.side_effect = lambda r, t, sheet=None: written.append(r)
        settings = {"takedown": {"parallel": parallel}}
        args = SimpleNamespace(headed=False, dry_run=False)
        done = {}
        with mock.patch.object(main, "_takedown", fake), mock.patch("builtins.print"):
            failed = main._run_takedown_rows(rows, settings, args, book, "取り下げ予定表", done)
        return failed, peak[0], done, sorted(written)

    def test_companies_run_at_the_same_time(self):
        rows = [row(2, "A社"), row(3, "B社"), row(4, "C社")]
        t0 = time.time()
        failed, peak, done, written = self.run_rows(rows)
        self.assertLess(time.time() - t0, 0.8)  # 1社ずつなら 0.9 秒かかる
        self.assertEqual((failed, peak, written), (0, 3, [2, 3, 4]))
        # 同時に書いても、すべての行と会社の記録が残る
        self.assertEqual(set(main._state("schedule.json")), {"td-2", "td-3", "td-4"})
        self.assertEqual(set(main._state("takedown.json")), {"A社", "B社", "C社"})

    def test_same_company_rows_run_one_by_one(self):
        failed, peak, done, written = self.run_rows([row(2, "A社"), row(3, "A社")])
        self.assertEqual((peak, written), (1, [2, 3]))

    def test_parallel_limit_and_failures(self):
        rows = [row(n, f"{n}社") for n in range(2, 7)]
        failed, peak, done, written = self.run_rows(rows, parallel=2, fail=("3社",))
        self.assertEqual((failed, peak, written), (1, 2, [2, 3, 4, 5, 6]))
        self.assertNotIn("td-3", done)  # 失敗した行は実行済みにしない


class TestMergeSameConditions(TestParallelRows):
    def test_keep_memos_of_same_company_are_merged(self):
        # 残すメモを1行に1つずつ書いた行は、会社ごとに1回の取り下げにまとめる（別々だと残したい原稿が消える）
        rows = [row(2, "A社", "m1"), row(3, "A社", "m2"), row(4, "A社", "m1"), row(5, "B社", "m3"),
                row(6, "A社", "m4", date_to=date(2026, 11, 9))]  # 期間が違う行は別に実行
        failed, peak, done, written = self.run_rows(rows)
        self.assertEqual(sorted(self.calls), [("A社", "m1\nm2"), ("A社", "m4"), ("B社", "m3")])
        self.assertEqual(written, [2, 3, 4, 5, 6])  # まとめた行すべてに結果を書く
        self.assertEqual(set(done), {"td-2", "td-3", "td-4", "td-5", "td-6"})


class TestPreparedConcurrent(unittest.TestCase):
    def test_other_company_entries_survive(self):
        with mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp())):
            def save(i):
                for k in range(5):
                    takedown._set_prepared(f"会社{i}", {"uploaded": k})
            ts = [threading.Thread(target=save, args=(i,)) for i in range(4)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            self.assertEqual(takedown._load_prepared(), {f"会社{i}": {"uploaded": 4} for i in range(4)})


if __name__ == "__main__":
    unittest.main()
