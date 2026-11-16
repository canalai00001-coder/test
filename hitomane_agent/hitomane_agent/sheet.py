"""【AI用】ヒトマネ 求人原稿自動生成 スプレッドシートを読む（サービスアカウント経由。書き込みはしない）。"""
from . import config
from .checks import Manuscript


class Spreadsheet:
    def __init__(self, settings: dict, book=None):
        self.settings = settings
        self._book = book

    @property
    def book(self):
        if self._book is None:
            import gspread

            gc = gspread.service_account(filename=str(config.ROOT / self.settings["service_account_file"]))
            self._book = gc.open_by_key(self.settings["spreadsheet_id"])
        return self._book

    def output_sheet_names(self) -> list[str]:
        prefix = self.settings["output_sheet_prefix"]
        return [ws.title for ws in self.book.worksheets() if ws.title.startswith(prefix)]

    def manuscript(self, name: str) -> Manuscript:
        return Manuscript(name, self.book.worksheet(name).get_all_values())
