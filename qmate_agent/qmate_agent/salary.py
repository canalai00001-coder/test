"""給与設定シート（入稿予定表と同じスプレッドシートの「給与設定」）。

職種・夜勤・会社・通勤/入寮ごとに、給与の金額帯を決めておくシート。ツールで原稿を作るときに、
予約の行に当てはまる設定を探して給与_下限・給与_上限を決める。

  幅に数（10000 など）を入れたとき：下限は「給与_下限」〜「給与_下限＋幅−1」の中から原稿ごとに重ならないように選ぶ。
                                    上限は「給与_上限」が空欄なら下限×1.25、入っていれば「給与_上限」に同じばらつきを足す。
                                    （幅 10000・上限空欄が、これまでの「33万」などの給与パターンと同じ）
  幅が空欄のとき：下限・上限を書いた値のまま使う（上限が空欄なら下限×1.25）。

通勤/入寮・職種・夜勤・会社は、空欄なら「すべて」。当てはまる行が複数あるときは、条件を多く書いた行を使う。
"""
import re

SHEET = "給与設定"
HEADERS = ["通勤/入寮", "職種", "夜勤", "会社", "給与形態", "給与_下限", "給与_上限", "幅", "メモ"]
NOTE = [
    ["【使い方】"],
    ["・1行に1つ、金額帯を書きます。通勤/入寮・職種・夜勤・会社は、空欄なら「すべて」です。"],
    ["・幅に 10000 を入れると、これまでどおりです（下限は 給与_下限〜+9,999円 から選び、上限は下限×1.25）。"],
    ["・幅が空欄なら、給与_下限・給与_上限をそのまま使います（上限が空欄なら下限×1.25）。"],
    ["・当てはまる行が複数あるときは、条件を多く書いた行を使います。"],
    ["・どの行にも当てはまらないときは、マニュアルの給与下限の表（ツールの設定）で決めます。"],
    ["・入稿前のチェックで、月給がマニュアルの給与下限を下回る原稿は止まります。"],
]


def _num(v, row: int, col: str) -> int | None:
    if v is None or str(v).strip() == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(round(v))
    s = str(v).strip().replace(",", "").replace("，", "").replace("円", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*万", s)
    if m:
        return int(round(float(m.group(1)) * 10000))
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return int(round(float(s)))
    raise ValueError(f"給与設定シート {row}行目の「{col}」が数字ではありません（{v}）")


def default_rows(rules: dict) -> list[list]:
    """今の決め方（rules.json の salary_floor）をそのまま書いた行。"""
    label = {job: f"{no}{job}" for no, job in rules.get("job_numbers", {}).items()}
    rows = []
    for job, floors in rules.get("salary_floor", {}).items():
        for night in ("夜勤あり", "夜勤なし"):
            if night in floors:
                rows.append(["通勤", label.get(job, job), night, "", "月給", floors[night], "", 10000,
                             "マニュアル「2026.10.1～給与下限」より"])
    return rows


def parse(values: list) -> list[dict]:
    if not values:
        return []
    head = [str(h).strip() for h in values[0]]
    missing = [h for h in HEADERS[:8] if h not in head]
    if missing:
        raise ValueError(f"給与設定シートの見出しに {'・'.join(missing)} がありません")
    col = {h: head.index(h) for h in HEADERS if h in head}
    get = lambda r, h: (r[col[h]] if col.get(h) is not None and col[h] < len(r) else "")
    out = []
    for n, r in enumerate(values[1:], start=2):
        lower = _num(get(r, "給与_下限"), n, "給与_下限")
        if lower is None:
            continue
        width = _num(get(r, "幅"), n, "幅")
        out.append({
            "row": n,
            "commute": str(get(r, "通勤/入寮")).strip(),
            "category": str(get(r, "職種")).strip(),
            "night": str(get(r, "夜勤")).strip(),
            "company": str(get(r, "会社")).strip(),
            "form": str(get(r, "給与形態")).strip() or "月給",
            "lower": lower,
            "upper": _num(get(r, "給与_上限"), n, "給与_上限"),
            "width": width if width and width > 1 else 0,
        })
    return out


def match(rules: list[dict], commute: str, category: str, night: bool, company: str) -> dict | None:
    """予約の行に当てはまる設定（条件を多く書いた行が優先。同じなら上の行）。"""
    job = lambda c: re.sub(r"^\d+", "", c)
    best, best_score = None, -1
    for r in rules:
        conds = [
            (r["commute"], r["commute"] == commute),
            (r["category"], r["category"] == category or job(r["category"]) == job(category)),
            (r["night"], r["night"] == ("夜勤あり" if night else "夜勤なし")),
            (r["company"], r["company"] == company),
        ]
        if any(v and not ok for v, ok in conds):
            continue
        score = sum(1 for v, _ in conds if v)
        if score > best_score:
            best, best_score = r, score
    return best


def describe(r: dict) -> str:
    unit = "時給" if r["form"] == "時給" else "月給"
    if r["width"]:
        lo = f"下限 {r['lower']:,}〜{r['lower'] + r['width'] - 1:,}円"
        up = (f"上限 {r['upper']:,}円＋下限と同じばらつき" if r["upper"] else "上限は下限×1.25")
    else:
        lo = f"下限 {r['lower']:,}円"
        up = f"上限 {r['upper']:,}円" if r["upper"] else "上限は下限×1.25"
    return f"給与設定シート {r['row']}行目（{unit}・{lo}・{up}）"
