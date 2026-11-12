"""読み取り回数の上限（429）対策：土台は1回の実行で1回だけ読む・結果を書けなくても続ける。"""
import unittest
from types import SimpleNamespace
from unittest import mock

from qmate_agent import __main__ as cli
from qmate_agent import sheet


class TestCache(unittest.TestCase):
    def test_base_values_are_read_once(self):
        calls = []
        ws = SimpleNamespace(title="会社情報", get_all_values=lambda **kw: calls.append(1) or [["会社名"]])
        fake = SimpleNamespace(worksheets=lambda: calls.append("meta") or [ws])
        with mock.patch.dict(sheet._VALUES, clear=True), mock.patch.dict(sheet._TITLES, clear=True):
            for _ in range(3):  # 行ごとに土台を開き直しても
                s = sheet.Spreadsheet({"spreadsheet_id": "BASE", "service_account_file": "x"})
                s._book = fake
                for name, get in s.sources():
                    self.assertEqual(get(), [["会社名"]])
        self.assertEqual(calls, ["meta", 1])

    def test_result_write_failure_does_not_stop(self):
        book = SimpleNamespace(write_plan_result=mock.Mock(side_effect=RuntimeError("APIError: [429]")))
        cli._write_result(book, 19, "失敗（…）")  # 例外を投げない
        book.write_plan_result.assert_called_once()
