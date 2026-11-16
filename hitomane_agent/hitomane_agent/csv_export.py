"""出力シートを、ヒトマネに取り込む CSV にする。

形は管理画面から取り出した CSV と同じ（2026-11-16 の画面調査）：Shift_JIS（cp932）・BOM なし・改行 CRLF・
セルの中の改行も CRLF・カンマ・引用符・改行を含むセルだけ "" で囲む・データ行の空欄は "" と書く（見出しは囲まない）。
スプレッドシートのセルの改行（LF）は CRLF にする。
"""
import csv
import io

from .checks import Manuscript

CRLF = "\r\n"


def _cell(v) -> str:
    return str(v).replace(CRLF, "\n").replace("\r", "\n").replace("\n", CRLF)


def _field(v: str, empty_quoted: bool) -> str:
    if v == "":
        return '""' if empty_quoted else ""
    if any(c in v for c in (",", '"', "\r", "\n")):
        return '"' + v.replace('"', '""') + '"'
    return v


def to_csv_bytes(ms: Manuscript, encoding: str = "cp932", newline: str = CRLF) -> bytes:
    """書けない文字があれば UnicodeEncodeError（チェックで先に見つけて止めている）。"""
    lines = [",".join(_field(_cell(h), False) for h in ms.headers)]
    for r in ms.raw_rows:
        lines.append(",".join(_field(_cell(v), True) for v in r))
    return "".join(line + newline for line in lines).encode(encoding)


def read_csv(data: bytes, name: str) -> Manuscript:
    """CSV（cp932、または BOM 付き・なしの UTF-8）を読む。取り出した CSV をそのまま取り込み直すときなど。"""
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("CSV の文字コードが分かりません（Shift_JIS か UTF-8 にしてください）")
    return Manuscript(name, list(csv.reader(io.StringIO(text, newline=""))))


def split_rows(ms: Manuscript, size: int) -> list[Manuscript]:
    """size 行ずつに分ける。分けたときは名前の後ろに _1, _2 … を付ける。"""
    if len(ms.raw_rows) <= size:
        return [ms]
    parts = []
    for n, i in enumerate(range(0, len(ms.raw_rows), size), start=1):
        parts.append(Manuscript(f"{ms.name}_{n}", [ms.headers] + ms.raw_rows[i:i + size]))
    return parts
