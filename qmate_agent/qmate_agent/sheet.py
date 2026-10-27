"""求人データの読み込みと、チェック結果・投稿結果の書き戻し。

Google スプレッドシートを直接読む（サービスアカウント）か、
テスト用に CSV を読む。どちらも「見出し行 + データ行」の形を前提にする。
"""
import csv
import unicodedata

from .config import ROOT


class Row:
    def __init__(self, row_number: int, values: dict):
        self.row_number = row_number  # シート上の行番号（見出しが1行目）
        self.values = values

    def get(self, column: str) -> str:
        v = self.values.get(column)
        return "" if v is None else str(v).strip()


def _clean_header(h: str) -> str:
    return unicodedata.normalize("NFKC", h or "").strip()


class Sheet:
    """読み込み元を隠すための薄いラッパー。"""

    def __init__(self, cfg: dict, source: str | None = None, csv_path: str | None = None):
        self.cfg = cfg
        self.source = source or cfg["source"]
        self.csv_path = csv_path or cfg.get("csv_path")
        self._ws = None
        self.headers: list[str] = []

    def _worksheet(self):
        if self._ws is None:
            import gspread

            gc = gspread.service_account(filename=str(ROOT / self.cfg["service_account_file"]))
            self._ws = gc.open_by_key(self.cfg["spreadsheet_id"]).worksheet(self.cfg["worksheet"])
        return self._ws

    def rows(self) -> list[Row]:
        if self.source == "csv":
            path = ROOT / self.csv_path if not str(self.csv_path).startswith("/") else self.csv_path
            with open(path, encoding="utf-8-sig", newline="") as f:
                table = list(csv.reader(f))
        else:
            table = self._worksheet().get_all_values()
        if not table:
            return []
        self.headers = [_clean_header(h) for h in table[0]]
        result = []
        for i, line in enumerate(table[1:], start=2):
            if not any(c.strip() for c in line):
                continue
            result.append(Row(i, dict(zip(self.headers, line))))
        return result

    def write(self, row: Row, column: str, value: str) -> None:
        """シートの指定列に書き戻す。列がなければ何もしない。CSV では書き戻さない。"""
        if self.source == "csv" or not column or column not in self.headers:
            return
        col = self.headers.index(column) + 1
        self._worksheet().update_cell(row.row_number, col, value)
