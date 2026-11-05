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

    def plan_table(self, sheet: str | None = None) -> list[list]:
        """入稿予定表（sheet を渡せばそのシート）を、書式を当てない値で読む（日付はシリアル値）。無ければ空。"""
        import gspread
        from gspread.utils import ValueRenderOption

        try:
            ws = self.book.worksheet(sheet or self.settings["plan_sheet"])
        except gspread.WorksheetNotFound:
            return []
        return ws.get_all_values(value_render_option=ValueRenderOption.unformatted)

    def write_plan_result(self, row: int, text: str, sheet: str | None = None) -> None:
        """入稿予定表（sheet を渡せばそのシート）の「実行結果」列に結果を書く。列が無ければ見出しの右隣に作る。"""
        from gspread.utils import rowcol_to_a1

        ws = self.book.worksheet(sheet or self.settings["plan_sheet"])
        head = [h.strip() for h in ws.row_values(1)]
        if "実行結果" in head:
            col = head.index("実行結果") + 1
        else:
            col = len(head) + 1
            ws.update([["実行結果"]], rowcol_to_a1(1, col), value_input_option="RAW")
        ws.update([[text]], rowcol_to_a1(row, col), value_input_option="RAW")

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

    def config_table(self) -> list[list]:
        """実行設定シート（書式を当てない値。作成日はシリアル値）。"""
        from gspread.utils import ValueRenderOption

        return self.book.worksheet(self.settings["config_sheet"]).get_all_values(
            value_render_option=ValueRenderOption.unformatted)

    def pending_config_rows(self, status_col: int) -> list[int]:
        """実行設定で、予約が入っているのに実行状況が空欄の行（GAS が次に生成する行）の行番号。"""
        from .schedule import CONFIG_DATA_START_ROW

        table = self.book.worksheet(self.settings["config_sheet"]).get_all_values()
        return [i for i, r in enumerate(table, start=1)
                if i >= CONFIG_DATA_START_ROW and any(c.strip() for c in r[:6])
                and not (r[status_col - 1].strip() if len(r) >= status_col else "")]

    def config_status(self, row: int, col: int) -> str:
        return (self.book.worksheet(self.settings["config_sheet"]).cell(row, col).value or "").strip()

    def sources(self) -> list:
        """原稿の生成用：[(シート名, 値を読む関数)]。中身は必要になったときだけ読む（書式を当てない値）。"""
        from gspread.utils import ValueRenderOption

        return [(ws.title, (lambda ws=ws: ws.get_all_values(value_render_option=ValueRenderOption.unformatted)))
                for ws in self.book.worksheets()]

    def usage_rows(self, sheet: str) -> list[list]:
        """使用履歴（見出しを除く）。シートが無ければ空。"""
        import gspread
        from gspread.utils import ValueRenderOption

        try:
            values = self.book.worksheet(sheet).get_all_values(value_render_option=ValueRenderOption.unformatted)
        except gspread.WorksheetNotFound:
            return []
        return values[1:]

    def write_usage(self, sheet: str, rows: list[list]) -> None:
        """使用履歴を書き戻す（GAS の flushUsageCache_ と同じく、2行目から全部書き直す。直近使用日は文字で）。"""
        import gspread

        try:
            ws = self.book.worksheet(sheet)
        except gspread.WorksheetNotFound:
            ws = self.book.add_worksheet(sheet, rows=max(len(rows) + 10, 100), cols=8)
            ws.update([["会社名(アカウント)", "職種番号(カテゴリ)", "職種名", "累計使用回数", "累計原稿数", "直近使用日",
                        "直近生成件数", "直近勤務地件数"]], "A1")
        clean = [[int(v) if isinstance(v, float) and v.is_integer() else v for v in r] for r in rows]
        if clean:
            ws.update(clean, "A2", value_input_option="RAW")

    def write_output_sheet(self, name: str, table: list[list]) -> None:
        """生成した原稿を「出力_…」シートとしても残す（GAS で作ったときと同じ見た目にしたいとき）。"""
        ws = self.book.add_worksheet(name, rows=len(table) + 1, cols=len(table[0]))
        for i in range(0, len(table), 2000):
            ws.update(table[i:i + 2000], f"A{i + 1}", value_input_option="RAW")

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
