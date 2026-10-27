"""出力シートを、いつも手で書き出しているのと同じ形の CSV にする。

見出し行（「職種名|必須」など）も含めて、シートの値をそのまま並べる。
"""
import csv
import io

from .checks import Manuscript


def to_csv_bytes(ms: Manuscript, encoding: str = "utf-8", newline: str = "\r\n") -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator=newline, quoting=csv.QUOTE_MINIMAL)
    width = len(ms.headers)
    w.writerow(ms.headers)
    for r in ms.raw_rows:
        w.writerow((r + [""] * width)[:width])
    return buf.getvalue().encode(encoding)
