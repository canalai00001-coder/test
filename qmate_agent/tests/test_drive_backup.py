"""入稿した原稿の Google ドライブへのバックアップを確かめる。Google には接続しない。"""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from qmate_agent import config, drive_backup

URL = "https://drive.google.com/drive/folders/1AbC_d-EF?usp=sharing"
SETTINGS = {"drive_backup": {"folder": URL}, "service_account_file": "x.json"}


class Resp:
    def __init__(self, data, status=200):
        self.status_code, self._data = status, data
        self.text = json.dumps(data)

    def json(self):
        return self._data


class FakeDrive:
    """フォルダ検索・作成・アップロードを覚えておく。"""
    def __init__(self, folders=None, upload_error=None):
        self.folders = dict(folders or {})
        self.uploaded, self.created = [], []
        self.upload_error = upload_error

    def get(self, url, params=None):
        if url.endswith("/files"):
            name = params["q"].split("name = '")[1].split("'")[0]
            return Resp({"files": [{"id": self.folders[name]}] if name in self.folders else []})
        return Resp(self.meta)

    def post(self, url, params=None, json=None, data=None, headers=None):
        if json is not None:
            self.created.append((json["name"], json["parents"]))
            self.folders[json["name"]] = "new_folder"
            return Resp({"id": "new_folder"})
        if self.upload_error:
            return Resp({"error": {"message": self.upload_error}}, 403)
        self.uploaded.append((data, headers))
        return Resp({"id": f"file{len(self.uploaded)}", "webViewLink": f"https://drive/file{len(self.uploaded)}"})


class TestBackup(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(config, "STATE_DIR", Path(tempfile.mkdtemp()))
        p.start()
        self.addCleanup(p.stop)
        self.csv = Path(tempfile.mkdtemp()) / "出力_G予定1_ArK株式会社_20261123.csv"
        self.csv.write_bytes("UID,メモ\r\n,テスト\r\n".encode("cp932"))
        self.logs = []

    def run_backup(self, drive, settings=SETTINGS):
        with mock.patch.object(drive_backup, "_session", return_value=drive):
            return drive_backup.backup([self.csv], settings, log=self.logs.append, when=datetime(2026, 11, 23))

    def test_folder_id(self):
        self.assertEqual(drive_backup.folder_id(URL), "1AbC_d-EF")
        self.assertEqual(drive_backup.folder_id("https://drive.google.com/open?id=XYZ"), "XYZ")
        self.assertEqual(drive_backup.folder_id(" XYZ "), "XYZ")

    def test_off_when_folder_blank(self):
        drive = FakeDrive()
        self.assertEqual(self.run_backup(drive, {"drive_backup": {"folder": ""}}), [])
        self.assertEqual(drive.uploaded, [])

    def test_makes_month_folder_and_uploads_csv_as_is(self):
        drive = FakeDrive()
        self.assertEqual(self.run_backup(drive), ["https://drive/file1"])
        self.assertEqual(drive.created, [("2026-11", ["1AbC_d-EF"])])
        body = drive.uploaded[0][0]
        self.assertIn(self.csv.read_bytes(), body)  # 中身はそのまま（Shift_JIS のまま）
        self.assertIn(self.csv.name.encode("utf-8"), body)
        state = json.loads((config.STATE_DIR / "drive_backup.json").read_text(encoding="utf-8"))
        self.assertEqual(state[str(self.csv)]["id"], "file1")
        self.assertEqual(drive_backup.failed(), [])

    def test_uses_existing_month_folder(self):
        drive = FakeDrive(folders={"2026-11": "month_id"})
        self.run_backup(drive)
        self.assertEqual(drive.created, [])

    def test_my_drive_error_does_not_raise_and_can_retry(self):
        drive = FakeDrive(upload_error="Service Accounts do not have storage quota.")
        self.assertEqual(self.run_backup(drive), [])
        self.assertIn("共有ドライブではありません", self.logs[-1])
        self.assertEqual(drive_backup.failed(), [str(self.csv)])
        self.run_backup(FakeDrive())  # 送り直すと失敗の記録が消える
        self.assertEqual(drive_backup.failed(), [])

    def test_check_folder_refuses_my_drive(self):
        drive = FakeDrive()
        drive.meta = {"name": "原稿", "mimeType": drive_backup.FOLDER}
        with mock.patch.object(drive_backup, "_session", return_value=drive):
            with self.assertRaisesRegex(RuntimeError, "マイドライブ"):
                drive_backup.check_folder(SETTINGS)
            drive.meta["driveId"] = "0AB"
            self.assertEqual(drive_backup.check_folder(SETTINGS), "原稿")


if __name__ == "__main__":
    unittest.main()
