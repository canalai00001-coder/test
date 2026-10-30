"""スプレッドシートの読み書き（サービスアカウント経由）。

GAS が作った「出力_…」シートを読み、検品シートの判定を確認し、
AIチェックの結果を「AIチェック結果」シートに書き出す。
"""
import csv
from pathlib import Path

from .checks import Manuscript
from .config import ROOT


class Spreadsheet:
    def __init__(self, settings: dict):
        self.settings = settings
        self._book = None

    @property
    def book(self):
        if self._book is None:
            import gspread

            gc = gspread.service_account(filename=str(ROOT / self.settings["service_account_file"]))
            self._book = gc.open_by_key(self.settings["spreadsheet_id"])
        return self._book

    def output_sheet_names(self) -> list[str]:
        prefix = self.settings["output_sheet_prefix"]
        return [ws.title for ws in self.book.worksheets() if ws.title.startswith(prefix)]

    def manuscript(self, name: str) -> Manuscript:
        return Manuscript(name, self.book.worksheet(name).get_all_values())

    def inspection_verdicts(self) -> dict[str, str]:
        """検品シートの {シート名: 判定}。検品シートがなければ空。"""
        import gspread

        s = self.settings
        try:
            table = self.book.worksheet(s["inspection_sheet"]).get_all_values()
        except gspread.WorksheetNotFound:
            return {}
        if not table:
            return {}
        head = table[0]
        ni, vi = head.index(s["inspection_name_column"]), head.index(s["inspection_verdict_column"])
        return {r[ni]: r[vi] for r in table[1:] if len(r) > max(ni, vi) and r[ni]}

    def plan_table(self) -> list[list[str]]:
        return self.book.worksheet(self.settings["plan_sheet"]).get_all_values()

    def write_plan_result(self, row: int, text: str) -> None:
        """入稿予定表の「実行結果」列に結果を書く（見出しも入れる）。"""
        ws = self.book.worksheet(self.settings["plan_sheet"])
        col = self.settings["plan_result_column"]
        ws.update([["実行結果"]], f"{col}1", value_input_option="RAW")
        ws.update([[text]], f"{col}{row}", value_input_option="RAW")

    def append_config_row(self, values: list) -> int:
        """実行設定の最後の予約行の下に1行足し、その行番号を返す。"""
        from .schedule import CONFIG_DATA_START_ROW

        ws = self.book.worksheet(self.settings["config_sheet"])
        table = ws.get_all_values()
        last = max([i for i, r in enumerate(table, start=1)
                    if i >= CONFIG_DATA_START_ROW and any(c.strip() for c in r[:6])], default=CONFIG_DATA_START_ROW - 1)
        row = last + 1
        ws.update([values], f"A{row}", value_input_option="USER_ENTERED")
        return row

    def config_status(self, row: int) -> str:
        from .schedule import CONFIG_STATUS_COL

        return (self.book.worksheet(self.settings["config_sheet"]).cell(row, CONFIG_STATUS_COL).value or "").strip()

    def write_results(self, rows: list[list[str]]) -> None:
        """AIチェック結果シートを作り直して書き込む。"""
        import gspread

        name = self.settings["result_sheet"]
        try:
            ws = self.book.worksheet(name)
            ws.clear()
        except gspread.WorksheetNotFound:
            ws = self.book.add_worksheet(name, rows=max(len(rows) + 10, 100), cols=10)
        ws.update(rows, "A1", value_input_option="RAW")


def manuscript_from_csv(path: str) -> Manuscript:
    """テスト用：出力シートを CSV で書き出したものを読む。"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        return Manuscript(Path(path).stem, list(csv.reader(f)))
