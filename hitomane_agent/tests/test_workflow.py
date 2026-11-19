"""check / upload の流れ（コマンド）。取り込みそのものは、にせの uploader に置き換える。"""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from hitomane_agent import __main__ as cli
from hitomane_agent import config
from hitomane_agent.checks import Manuscript
from hitomane_agent.csv_export import to_csv_bytes
from hitomane_agent.uploader import UploadResult
from tests.samples import row, table


class FakeUploader:
    calls = []
    ok = True
    total_value = 100
    branches = [{"code": "B001", "name": "テスト株式会社"}]
    infos = []

    def __init__(self, info, opts, out_dir, headed=False, log=print):
        FakeUploader.infos.append(info)

    def total(self):
        return FakeUploader.total_value

    def account(self):
        return {"total": FakeUploader.total_value, "branches": FakeUploader.branches}

    def upload(self, files, old_format=False, register_work=True):
        FakeUploader.calls.append([Path(f).read_bytes() for f in files])
        FakeUploader.old_formats = getattr(FakeUploader, "old_formats", []) + [old_format]
        return [UploadResult(Path(f).name, FakeUploader.ok, "取り込みが終わりました（完了）") for f in files]


def fake_login_info(settings, book=None, company=None):
    code = company or "m66w"
    return {"login_id": "Minami", "password": "pw", "url": f"http://x/{code}/", "company": f"{code}社", "code": code}


class Base(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        for name, value in (("OUTPUT_DIR", d / "output"), ("STATE_DIR", d / "state")):
            p = mock.patch.object(config, name, value)
            p.start()
            self.addCleanup(p.stop)
        for target, value in (("hitomane_agent.uploader.HitomaneUploader", FakeUploader),
                              ("hitomane_agent.accounts.login_info", fake_login_info)):
            p = mock.patch(target, value)
            p.start()
            self.addCleanup(p.stop)
        FakeUploader.calls, FakeUploader.ok, FakeUploader.total_value = [], True, 100
        FakeUploader.branches, FakeUploader.infos = [{"code": "B001", "name": "テスト株式会社"}], []
        self.dir = d
        self.csv = d / "ヒトマネ出力_テスト.csv"
        self.write(row())

    def write(self, *rows):
        self.csv.write_bytes(to_csv_bytes(Manuscript("x", table(*rows))))

    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(list(argv))
        return code, buf.getvalue()


class TestWorkflow(Base):
    def test_check_then_upload(self):
        code, out = self.run_cli("check", "--csv", str(self.csv))
        self.assertEqual(code, 0, out)
        self.assertIn("判定 OK", out)
        self.assertTrue((config.OUTPUT_DIR / "ヒトマネ出力_テスト" / "report.html").exists())
        code, out = self.run_cli("upload", "--csv", str(self.csv), "--yes")
        self.assertEqual(code, 0, out)
        self.assertEqual(FakeUploader.calls, [[self.csv.read_bytes()]])  # シートと同じ形の CSV を取り込む
        self.assertIn("全件数は 100件", out)

    def test_upload_without_check_stops(self):
        code, out = self.run_cli("upload", "--csv", str(self.csv), "--yes")
        self.assertEqual(code, 1)
        self.assertIn("チェックをしていません", out)
        self.assertEqual(FakeUploader.calls, [])

    def test_changed_after_check_stops(self):
        self.run_cli("check", "--csv", str(self.csv))
        self.write(row(**{"PR": "書き換えた"}))
        code, out = self.run_cli("upload", "--csv", str(self.csv), "--yes")
        self.assertEqual(code, 1)
        self.assertIn("内容が変わっています", out)

    def test_ng_stops(self):
        self.write(row(**{"募集番号": ""}))
        code, _ = self.run_cli("check", "--csv", str(self.csv))
        self.assertEqual(code, 2)
        code, out = self.run_cli("upload", "--csv", str(self.csv), "--yes")
        self.assertIn("NG", out)
        self.assertEqual(FakeUploader.calls, [])

    def test_same_content_twice_stops(self):
        self.run_cli("check", "--csv", str(self.csv))
        self.run_cli("upload", "--csv", str(self.csv), "--yes")
        code, out = self.run_cli("upload", "--csv", str(self.csv), "--yes")
        self.assertEqual(code, 1)
        self.assertIn("入稿済み", out)
        self.assertEqual(len(FakeUploader.calls), 1)

    def test_failed_upload_is_not_recorded(self):
        FakeUploader.ok = False
        self.run_cli("check", "--csv", str(self.csv))
        code, _ = self.run_cli("upload", "--csv", str(self.csv), "--yes")
        self.assertEqual(code, 2)
        FakeUploader.ok = True
        code, _ = self.run_cli("upload", "--csv", str(self.csv), "--yes")  # 失敗したものは、もう一度入れられる
        self.assertEqual(code, 0)

    def test_dry_run_does_not_upload(self):
        self.run_cli("check", "--csv", str(self.csv))
        code, out = self.run_cli("upload", "--csv", str(self.csv), "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(FakeUploader.calls, [])
        self.assertTrue((config.OUTPUT_DIR / "ヒトマネ出力_テスト" / "ヒトマネ出力_テスト.csv").exists())

    def test_asks_before_upload(self):
        self.run_cli("check", "--csv", str(self.csv))
        with mock.patch("builtins.input", return_value="n"):
            code, out = self.run_cli("upload", "--csv", str(self.csv))
        self.assertEqual(code, 1)
        self.assertEqual(FakeUploader.calls, [])

    def test_warns_near_limit(self):
        FakeUploader.total_value = 50000
        self.run_cli("check", "--csv", str(self.csv))
        _, out = self.run_cli("upload", "--csv", str(self.csv), "--yes")
        self.assertIn("上限を超えます", out)

    def test_splits_large_sheet(self):
        rows = [row(**{"募集番号": f"t{i}"}) for i in range(3)]  # 勤務地の重複は注意だけ（入稿はできる）
        self.write(*rows)
        rules = config.load("rules.json")
        rules["max_rows_per_file"] = 2
        with mock.patch.object(config, "load", side_effect=lambda n: rules if n == "rules.json" else _load(n)):
            self.run_cli("check", "--csv", str(self.csv))
            code, out = self.run_cli("upload", "--csv", str(self.csv), "--yes", "--dry-run")
        self.assertIn("ヒトマネ出力_テスト_1.csv", out)
        self.assertIn("ヒトマネ出力_テスト_2.csv", out)


class TestCompany(Base):
    def setUp(self):
        super().setUp()
        self.run_cli("check", "--csv", str(self.csv))

    def test_company_is_shown_and_used(self):
        code, out = self.run_cli("upload", "--csv", str(self.csv), "--yes", "--company", "o3h3")
        self.assertEqual(code, 0, out)
        self.assertIn("入れる会社: o3h3社（o3h3）", out)
        self.assertEqual(FakeUploader.infos[-1]["url"], "http://x/o3h3/")

    def test_branch_of_other_company_stops(self):
        FakeUploader.branches = [{"code": "G001", "name": "GritMate株式会社"}]
        code, out = self.run_cli("upload", "--csv", str(self.csv), "--yes", "--company", "o3h3")
        self.assertEqual(code, 1)
        self.assertIn("拠点にない拠点コードがあります：B001", out)
        self.assertIn("G001 GritMate株式会社", out)
        self.assertEqual(FakeUploader.calls, [])

    def test_no_branches_stops(self):
        FakeUploader.branches = []
        code, out = self.run_cli("upload", "--csv", str(self.csv), "--yes")
        self.assertEqual(code, 1)
        self.assertIn("拠点の一覧を読めませんでした", out)

    def test_uploaded_is_per_company(self):
        self.assertEqual(self.run_cli("upload", "--csv", str(self.csv), "--yes", "--company", "m66w")[0], 0)
        code, out = self.run_cli("upload", "--csv", str(self.csv), "--yes", "--company", "m66w")
        self.assertIn("入稿済み", out)
        code, out = self.run_cli("upload", "--csv", str(self.csv), "--yes", "--company", "o3h3")
        self.assertEqual(code, 0, out)  # 別の会社には入れられる
        self.assertEqual(len(FakeUploader.calls), 2)


_load = config.load


if __name__ == "__main__":
    unittest.main()
