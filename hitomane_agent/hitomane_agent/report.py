"""チェック結果を、入稿してよいか判断するための HTML にまとめる。"""
import html
from datetime import datetime

from .checks import status_of

STATUS_COLOR = {"OK": "#1a7f37", "要確認": "#9a6700", "NG": "#cf222e"}
SEV_LABEL = {"error": "エラー", "warning": "注意"}
PREVIEW_COLUMNS = ["募集番号", "開始日", "終了日", "ステータス", "お仕事番号", "拠点コード", "拠点", "募集職種",
                   "基本給_最低額", "基本給_最高額", "勤務地_都道府県", "勤務地_市区町村", "画像名1", "勤務時間_補足", "休日・休暇"]


def render(name: str, rows: list[dict], sheet_issues: list, results: list[list]) -> str:
    esc = html.escape
    overall = status_of(sheet_issues + [i for r in results for i in r])
    p = [
        f"<!doctype html><meta charset='utf-8'><title>{esc(name)} チェック結果</title>",
        "<style>body{font-family:sans-serif;margin:24px;color:#1f2328;max-width:1200px}"
        "table{border-collapse:collapse;margin:8px 0 20px;width:100%}td,th{border:1px solid #d0d7de;"
        "padding:4px 8px;vertical-align:top;font-size:13px}th{background:#f6f8fa;text-align:left;white-space:nowrap}"
        ".error{color:#cf222e}.warning{color:#9a6700}h2{margin-top:32px;border-bottom:1px solid #d0d7de}"
        "pre{white-space:pre-wrap;margin:0;font-family:inherit}</style>",
        f"<h1>{esc(name)}</h1>",
        f"<p>{datetime.now():%Y-%m-%d %H:%M} 作成 / 原稿{len(rows)}件 / 判定 "
        f"<b style='color:{STATUS_COLOR[overall]}'>{overall}</b></p>",
    ]

    def issue_table(issues):
        out = ["<table><tr><th>種類</th><th>列</th><th>内容</th></tr>"]
        for i in issues:
            out.append(f"<tr><td class='{i.severity}'>{SEV_LABEL[i.severity]}</td><td>{esc(i.column)}</td>"
                       f"<td>{esc(i.message)}</td></tr>")
        out.append("</table>")
        return "".join(out)

    if sheet_issues:
        p.append("<h2>シート全体</h2>" + issue_table(sheet_issues))
    if not rows:
        return "".join(p)

    p.append("<table><tr><th>行</th><th>募集番号</th><th>募集職種</th><th>勤務地</th><th>判定</th></tr>")
    for n, (row, issues) in enumerate(zip(rows, results), start=2):
        st = status_of(issues)
        p.append(f"<tr><td><a href='#r{n}'>{n}</a></td><td>{esc(row.get('募集番号', ''))}</td>"
                 f"<td>{esc(row.get('募集職種', ''))}</td>"
                 f"<td>{esc(row.get('勤務地_都道府県', '') + row.get('勤務地_市区町村', ''))}</td>"
                 f"<td style='color:{STATUS_COLOR[st]};font-weight:bold'>{st}</td></tr>")
    p.append("</table>")

    for n, (row, issues) in enumerate(zip(rows, results), start=2):
        if not issues:
            continue
        st = status_of(issues)
        p.append(f"<h2 id='r{n}'>{n}行目 <span style='color:{STATUS_COLOR[st]}'>{st}</span></h2>")
        p.append(issue_table(issues))
        p.append("<details><summary>原稿の主な項目</summary><table>")
        for c in PREVIEW_COLUMNS:
            p.append(f"<tr><th>{esc(c)}</th><td><pre>{esc(row.get(c, ''))}</pre></td></tr>")
        p.append("</table></details>")
    return "".join(p)
