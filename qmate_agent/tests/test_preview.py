"""テスト（入稿しないで作る）→ 画面で書き直す → そのまま入稿。"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from qmate_agent import __main__ as cli
from qmate_agent import config, preview
from qmate_agent.checks import Manuscript
from tests.fixtures import clean_row, table

COMPANY = {"name": "canal benefits株式会社", "email": "canal.saiyou@gmail.com",
           "memo_name": "canal benefits株式会社/A", "others": {}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for p in (mock.patch.object(config, "OUTPUT_DIR", self.tmp / "output"),
                  mock.patch.object(config, "STATE_DIR", self.tmp / "state")):
            p.start()
            self.addCleanup(p.stop)

    def make(self, *rows):
        meta = {"row": 3, "plan_key": "KEY", "company": COMPANY["name"], "category": "6重め", "commute": "通勤",
                "night": "夜勤あり", "count": len(rows), "company_info": COMPANY, "title_counts": {"組立": len(rows)},
                "usage_category": "6重め"}
        return preview.save(meta, Manuscript("出力_G予定3_test", table(*rows)))


class TestPreviewFiles(Base):
    def test_edit_fixes_ng(self):
        name = self.make(clean_row(休日休暇="#REF!"))
        m = preview.meta(name)
        self.assertEqual((m["status"], m["counts"]["NG"]), ("NG", 1))
        d = preview.detail(name)
        self.assertEqual([r["index"] for r in d["rows"]], [0])
        self.assertEqual(d["rows"][0]["values"], {"休日休暇": "#REF!"})
        preview.edit(name, 0, "休日休暇", "＜休日＞\n・年間休日120日")
        self.assertEqual(preview.meta(name)["status"], "OK")
        self.assertEqual(preview.cell(name, 0, "休日休暇"), "＜休日＞\n・年間休日120日")
        self.assertEqual(preview.detail(name)["rows"], [])
        self.assertEqual(len(preview.detail(name, only_issues=False)["rows"]), 1)
        self.assertEqual(preview.listing()[0]["name"], name)

    def test_wrong_email_is_ng_and_can_be_fixed(self):
        name = self.make(clean_row(応募時メール送信先1="other@example.com"))
        self.assertEqual(preview.meta(name)["status"], "NG")
        preview.edit(name, 0, "応募時メール送信先1", "canal.saiyou@gmail.com")
        self.assertEqual(preview.meta(name)["status"], "OK")

    def test_names_cannot_leave_the_folder(self):
        for bad in ("../state", "3行目_x", ""):
            with self.assertRaises(ValueError):
                preview.meta(bad)


class TestCommands(Base):
    def plan(self, key="KEY"):
        return SimpleNamespace(row=3, key=key, company=COMPANY["name"], category="6重め", night=True, count=2,
                               commute="通勤", status="下書き")

    def test_preview_command_does_not_upload_or_record(self):
        settings = config.load("settings.json")
        settings["schedule_targets"]["通勤"]["engine"] = "python"
        ms = Manuscript("出力_G予定3_test", table(clean_row()))
        ms.title_counts, ms.category = {"組立": 1}, "6重め"
        load = config.load
        with mock.patch.object(cli.config, "load", side_effect=lambda n: settings if n == "settings.json" else load(n)), \
                mock.patch.object(cli, "_plan_row", return_value=self.plan()), \
                mock.patch.object(cli, "_generate_locally", return_value=ms) as gen, \
                mock.patch.object(cli, "_company_info", return_value=COMPANY), \
                mock.patch.object(cli, "cmd_upload") as up:
            self.assertEqual(cli.cmd_preview(SimpleNamespace(row=3)), 0)
        self.assertFalse(gen.call_args.kwargs["record_usage"])
        up.assert_not_called()
        self.assertEqual(preview.listing()[0]["status"], "OK")

    def test_upload_preview_uses_edited_content(self):
        name = self.make(clean_row(休日休暇="#REF!"))
        preview.edit(name, 0, "休日休暇", "直した休日")
        sent, written = {}, {}
        book = SimpleNamespace(usage_rows=lambda s: [], write_usage=lambda s, rows: written.setdefault("usage", rows),
                               write_plan_result=lambda r, t: written.setdefault("result", (r, t)))
        with mock.patch.object(cli, "_plan_row", return_value=self.plan()), \
                mock.patch.object(cli, "_spreadsheet", return_value=book), \
                mock.patch.object(cli, "cmd_check", return_value=0), \
                mock.patch.object(cli, "cmd_upload", side_effect=lambda a: sent.setdefault("ms", a.manuscript) and 0):
            self.assertEqual(cli.cmd_upload_preview(SimpleNamespace(name=name)), 0)
        self.assertEqual(sent["ms"].rows[0]["休日休暇"], "直した休日")
        self.assertEqual(written["usage"][0][:3], [COMPANY["name"], "6重め", "組立"])
        self.assertTrue(written["result"][1].startswith("入稿済み"))
        self.assertTrue(preview.meta(name)["uploaded_at"])
        # 2回目は入稿しない
        with mock.patch.object(cli, "_plan_row", return_value=self.plan()):
            self.assertEqual(cli.cmd_upload_preview(SimpleNamespace(name=name)), 1)

    def test_plan_changed_after_test_is_refused(self):
        name = self.make(clean_row())
        with mock.patch.object(cli, "_plan_row", return_value=self.plan(key="CHANGED")), \
                mock.patch.object(cli, "cmd_upload") as up:
            self.assertEqual(cli.cmd_upload_preview(SimpleNamespace(name=name)), 1)
        up.assert_not_called()


class TestTodayBatch(Base):
    def test_only_today_and_not_done(self):
        from datetime import date
        today = date.today()
        plans = [SimpleNamespace(row=r, key=f"K{r}", run_date=d) for r, d in
                 ((2, today), (3, today), (4, today), (5, date(2020, 1, 1)))]
        cli._save_state("schedule.json", {"K3": {"finished_at": "x"}})   # 3行目はツールで入稿済み
        book = SimpleNamespace(plan_table=lambda *a: [["実行結果"]])
        seen = []
        with mock.patch.object(cli, "_spreadsheet", return_value=book), \
                mock.patch("qmate_agent.schedule.read_plan", return_value=plans), \
                mock.patch.object(cli, "_plan_results", return_value={4: "入稿済み（11/10 10:00）"}), \
                mock.patch.object(cli, "_preview_one", side_effect=lambda s, r, p: seen.append(p.row) or 0):
            self.assertEqual(cli.cmd_preview(SimpleNamespace(today=True, row=None)), 0)
        self.assertEqual(seen, [2])

    def test_is_done(self):
        self.assertTrue(cli.is_done("K", "", {"K": {}}))
        self.assertTrue(cli.is_done("X", "入稿済み（11/10）", {}))
        self.assertTrue(cli.is_done("X", "取り下げ済み（11/10）", {}))
        self.assertFalse(cli.is_done("X", "テスト：CSV作成まで（11/10）", {}))
        self.assertFalse(cli.is_done("X", "失敗（11/10）", {}))
