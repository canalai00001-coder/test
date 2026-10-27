"""チェック結果を、人が承認判断するための HTML にまとめる。"""
import html
from datetime import datetime

STATUS_COLOR = {"OK": "#1a7f37", "要確認": "#9a6700", "NG": "#cf222e"}
SEV_LABEL = {"error": "エラー", "warning": "注意", "info": "参考"}


def render(results: list[dict], labels: dict) -> str:
    esc = html.escape
    parts = [
        "<!doctype html><meta charset='utf-8'><title>求人チェック結果</title>",
        "<style>body{font-family:sans-serif;margin:24px;color:#1f2328}"
        "table{border-collapse:collapse;margin:8px 0 24px}td,th{border:1px solid #d0d7de;padding:4px 8px;"
        "vertical-align:top;font-size:14px}th{background:#f6f8fa;text-align:left;white-space:nowrap}"
        ".st{font-weight:bold}.error{color:#cf222e}.warning{color:#9a6700}.info{color:#57606a}"
        "h2{margin-top:32px;border-bottom:1px solid #d0d7de}</style>",
        f"<h1>求人チェック結果</h1><p>{datetime.now():%Y-%m-%d %H:%M} 作成 / {len(results)}件</p>",
        "<table><tr><th>行</th><th>求人No</th><th>職種名</th><th>判定</th><th>件数</th></tr>",
    ]
    for r in results:
        job = r["job"]
        counts = " / ".join(f"{SEV_LABEL[s]}{sum(1 for i in r['issues'] if i.severity == s)}"
                            for s in ("error", "warning", "info"))
        parts.append(
            f"<tr><td>{r['row']}</td><td><a href='#r{r['row']}'>{esc(job.get('job_no', ''))}</a></td>"
            f"<td>{esc(job.get('title', ''))}</td>"
            f"<td class='st' style='color:{STATUS_COLOR[r['status']]}'>{r['status']}</td><td>{counts}</td></tr>")
    parts.append("</table>")

    for r in results:
        job = r["job"]
        parts.append(f"<h2 id='r{r['row']}'>{r['row']}行目 {esc(job.get('job_no', ''))} "
                     f"<span style='color:{STATUS_COLOR[r['status']]}'>{r['status']}</span></h2>")
        if r.get("summary"):
            parts.append(f"<p>AIコメント: {esc(r['summary'])}</p>")
        if r["issues"]:
            parts.append("<table><tr><th>種類</th><th>項目</th><th>内容</th><th>修正案</th><th>判定元</th></tr>")
            for i in r["issues"]:
                parts.append(f"<tr><td class='{i.severity}'>{SEV_LABEL[i.severity]}</td>"
                             f"<td>{esc(labels.get(i.field, i.field))}</td><td>{esc(i.message)}</td>"
                             f"<td>{esc(i.suggestion)}</td><td>{'AI' if i.source == 'ai' else 'ルール'}</td></tr>")
            parts.append("</table>")
        parts.append("<details><summary>投稿される内容</summary><table>")
        for k, v in job.items():
            parts.append(f"<tr><th>{esc(labels.get(k, k))}</th><td>{esc(v).replace(chr(10), '<br>')}</td></tr>")
        parts.append("</table></details>")
    return "".join(parts)
