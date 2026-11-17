"""入稿予定表（Q-mate 版の入稿予定表のヒトマネ版）。

担当者は【AI用】ヒトマネ 求人原稿自動生成 の「入稿予定表」シートに予定を入れるだけ。ツールが実行日の行を拾い、
原稿を作る（generator。GAS の③と同じ作り方）→ チェック → 選んだ会社のヒトマネに入稿 → 実行結果を書き戻す、までを行う。

- 1行＝1回の生成予約（GAS の「ヒトマネ実行設定」の1行と同じ中身）。グループは行ごとに分ける（グループ番号「予定<行>」）。
- 募集番号の先頭が空欄なら、その会社にツールで前回入稿した続きの番号を使う（state/entry_numbers.json）。
  初めての会社は入れてもらう。
- 入稿した原稿の職種名・仕事内容は、このパソコンの記録（state/usage_local.json）に残し、次に作るときに使用履歴と合わせて
  避ける。土台の使用履歴シートには書かない（GAS から切り替えるときに書く）。
- 取り下げは予定表では行わない（取り下げは担当者が条件と件数を確かめてから行う決まりのため）。
"""
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import config, generator

SHEET = "入稿予定表"
LIST_SHEET = "_入稿予定表_プルダウン（自動生成・編集不要）"
# 見出し（改行のあとは担当者向けの補足。読むときは改行の前だけを見る）
HEADERS = ["実行日", "会社", "職種", "夜勤有無", "通勤/入寮", "雇用形態", "入稿ステータス",
           "原稿数\n(空欄=勤務地の数)", "画像カテゴリー", "給与パターン\n(空欄=基本)",
           "職種名選択\n(6重め/7軽めのみ・必須)", "タイトル末尾ワード\n(空欄=タイトルシートの値)",
           "募集番号の先頭\n(空欄=前回の続き)", "実行結果", "メモ"]
REQUIRED = ("実行日", "会社", "職種")
DEFAULTS = {"通勤/入寮": "通勤", "雇用形態": "正社員", "入稿ステータス": "掲載", "給与パターン": "基本"}


def header_name(h) -> str:
    return str(h).strip().split("\n")[0].strip()


@dataclass
class PlanRow:
    row: int
    run_date: date | None
    company: str
    category: str
    night: bool
    commute: str
    employment: str
    status: str
    count: str
    image: str
    salary: str
    title_choice: str
    dedup_word: str
    prefix: str
    result: str

    @property
    def key(self) -> str:
        """実行済みかどうかを覚えるための印（中身が変われば別の予定とみなす）。"""
        d = self.run_date.isoformat() if self.run_date else "日付なし"
        return "|".join([str(self.row), d, self.company, self.category, "夜勤あり" if self.night else "夜勤なし",
                         self.commute, self.employment, self.status, self.count, self.image, self.salary,
                         self.title_choice, self.dedup_word, self.prefix])


def parse_date(s, today: date) -> date | None:
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return date(1899, 12, 30) + timedelta(days=int(s))  # 日付のシリアル値
    s = str(s or "").strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})[/月](\d{1,2})日?", s)
    return date(today.year, int(m[1]), int(m[2])) if m else None


def read_plan(table: list[list], today: date) -> list[PlanRow]:
    """入稿予定表（1行目が見出し）から、実行日・会社・職種の入った行を読む。"""
    if not table:
        return []
    head = [header_name(h) for h in table[0]]
    missing = [n for n in REQUIRED if n not in head]
    if missing:
        raise RuntimeError(f"入稿予定表の見出しに「{'」「'.join(missing)}」がありません（操作画面の「入稿予定表を作る・整える」で直せます）")
    col = {header_name(h): i for i, h in enumerate(HEADERS) if header_name(h) in head}
    col = {n: head.index(n) for n in col}
    rows = []
    for i, r in enumerate(table[1:], start=2):
        raw = lambda n: r[col[n]] if n in col and col[n] < len(r) else ""
        get = lambda n: str(raw(n)).strip()
        if not (get("会社") and get("職種")):
            continue
        night = get("夜勤有無")
        rows.append(PlanRow(i, parse_date(raw("実行日"), today), get("会社"), get("職種"),
                            night.upper() in ("TRUE", "あり", "夜勤あり", "1", "○"),
                            get("通勤/入寮") or DEFAULTS["通勤/入寮"], get("雇用形態") or DEFAULTS["雇用形態"],
                            get("入稿ステータス") or DEFAULTS["入稿ステータス"], get("原稿数"), get("画像カテゴリー"),
                            get("給与パターン") or DEFAULTS["給与パターン"], get("職種名選択"), get("タイトル末尾ワード"),
                            get("募集番号の先頭"), get("実行結果")))
    return rows


def title_choice(p: PlanRow) -> str:
    """職種名選択を GAS のプルダウンと同じ「7軽め｜職種名」の形にそろえる。"""
    t = p.title_choice.strip()
    return t if not t or "｜" in t else f"{p.category}｜{t}"


def to_targets(plans: list[PlanRow], today: date, numbers: dict) -> list[generator.Target]:
    """予定の行 → 生成の予約（1行＝1グループ「予定<行>」）。募集番号の先頭が空なら、会社ごとの前回の続きを最初の行に使う。"""
    out, first = [], set()
    for p in plans:
        prefix = p.prefix
        if not prefix and p.company not in first:
            prefix = numbers.get(p.company, "")
            if not prefix:
                raise RuntimeError(f"{p.row}行目：{p.company} をツールで入稿するのは初めてのため、「募集番号の先頭」を入れてください"
                                   "（例：canalbenefits200001）")
        first.add(p.company)
        count = p.count.replace(",", "")
        out.append(generator.Target(
            sheet_row=p.row, group_id=f"予定{p.row}", seq=1, creation_date=f"{today:%Y/%m/%d}", commute=p.commute,
            employment=p.employment, category=p.category, company=p.company, format="新FMT",
            count=None if count == "" else (int(count) if count.isdigit() else float("nan")), count_raw=p.count,
            entry_prefix=prefix, status=p.status, image_category=p.image, salary_pattern=p.salary,
            night_shift="夜勤あり" if p.night else "夜勤なし", paired_title=title_choice(p),
            title_dedup_word=p.dedup_word, exec_status=""))
    return out


# ---------------------------------------------------------------- このパソコンの記録

def _load(name: str):
    path = config.STATE_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _save(name: str, data) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    (config.STATE_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def entry_numbers() -> dict:
    """会社ごとの、次に使う募集番号（ツールで入稿したときに進める）。"""
    return _load("entry_numbers.json") or {}


def next_number(last: str) -> str:
    return generator._entry_numbers(last)(1)


def remember_number(company: str, last_entry: str) -> None:
    nums = entry_numbers()
    nums[company] = next_number(last_entry)
    _save("entry_numbers.json", nums)


def record_usage(meta: dict) -> None:
    """入稿した原稿の職種名・仕事内容を、このパソコンの使用履歴に足す（土台のシートには書かない）。"""
    data = _load("usage_local.json") or {"titles": [], "contents": []}
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    company, category = meta["company"], meta["category"]
    for tc in meta.get("title_counts", []):
        for title, n in tc.items():
            data["titles"].append([company, category, title, "1", str(n), stamp])
    for cc in meta.get("content_counts", []):
        data["contents"].extend([company, category, c] for c in cc)
    _save("usage_local.json", data)


def merge_usage(usage: generator.Usage) -> generator.Usage:
    """土台の使用履歴に、このパソコンでツールが入稿した分を足す（同じ実行の後ろの予約が避けるのと同じ考え方）。"""
    data = _load("usage_local.json") or {}
    usage.title_rows.extend([list(r) for r in data.get("titles", [])])
    for comp, cat, content in data.get("contents", []):
        usage.content_used.setdefault(f"{comp}||{cat}", set()).add(content)
    return usage


def done() -> dict:
    return _load("schedule.json") or {}


def mark_done(p: PlanRow, text: str) -> None:
    d = done()
    d[p.key] = {"row": p.row, "result": text, "finished_at": datetime.now().isoformat(timespec="seconds")}
    _save("schedule.json", d)


# ---------------------------------------------------------------- シートを作る・整える（書き込み）

def _q(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def setup_sheet(book, bank: generator.Bank) -> list[str]:
    """入稿予定表が無ければ作り、見出し・プルダウン・1行目の固定を整える。入っている予定は消さない。

    プルダウンの候補（会社・職種・画像カテゴリー・職種名選択）は、土台から作った隠しシートに置いて参照する。
    戻り値は行ったことの説明。"""
    done_list = []
    names = [ws.title for ws in book.worksheets()]
    if SHEET not in names:
        ws = book.add_worksheet(SHEET, rows=1000, cols=len(HEADERS))
        ws.update(range_name="A1", values=[HEADERS])
        done_list.append(f"「{SHEET}」シートを作りました")
    else:
        ws = book.worksheet(SHEET)
        head = [header_name(h) for h in (ws.row_values(1) or [])]
        add = [h for h in HEADERS if header_name(h) not in head]
        if not head:
            ws.update(range_name="A1", values=[HEADERS])
            done_list.append("見出しを書きました")
        elif add:
            if ws.col_count < len(head) + len(add):
                ws.add_cols(len(head) + len(add) - ws.col_count)
            ws.update(range_name=f"{_col(len(head) + 1)}1", values=[add])
            done_list.append(f"足りない列を右に足しました：{'、'.join(header_name(h) for h in add)}")
    head = [header_name(h) for h in ws.row_values(1)]
    rows = max(ws.row_count, 1000)

    companies = list(bank.companies)
    categories = [generator.CATEGORY_NUMBER_LABEL[c] for c in generator.CATEGORY_NAMES
                  if bank.job_titles.get(generator.CATEGORY_NUMBER_LABEL[c]) or bank.paired_job_data.get(c)]
    images = list(bank.images_by_category)
    titles = [f"{generator.CATEGORY_NUMBER_LABEL[c]}｜{e['title']}" for c in ("重め", "軽め")
              for e in bank.paired_job_data.get(c, [])]
    lists = [("会社", companies), ("職種", categories), ("画像カテゴリー", images), ("職種名選択", titles)]
    if LIST_SHEET in names:
        lst = book.worksheet(LIST_SHEET)
        lst.clear()
    else:
        lst = book.add_worksheet(LIST_SHEET, rows=max(len(x) for _, x in lists) + 10, cols=len(lists))
    need = max(len(x) for _, x in lists) + 1
    if lst.row_count < need:
        lst.add_rows(need - lst.row_count)
    table = [[n for n, _ in lists]] + [[(x[i] if i < len(x) else "") for _, x in lists] for i in range(need - 1)]
    lst.update(range_name="A1", values=table)

    def cell_range(col_name):
        c = head.index(col_name)
        return {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": rows, "startColumnIndex": c, "endColumnIndex": c + 1}

    def rule(col_name, condition, strict=False):
        return {"setDataValidation": {"range": cell_range(col_name), "rule": {
            "condition": condition, "showCustomUi": True, "strict": strict}}}

    one_of = lambda vals: {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in vals]}
    in_list = lambda i, n: {"type": "ONE_OF_RANGE",
                            "values": [{"userEnteredValue": f"={_q(LIST_SHEET)}!{_col(i + 1)}2:{_col(i + 1)}{n + 1}"}]}
    reqs = [rule("実行日", {"type": "DATE_IS_VALID"}),
            rule("夜勤有無", {"type": "BOOLEAN"}),
            rule("通勤/入寮", one_of(["通勤", "入寮"])),
            rule("雇用形態", one_of(["正社員", "契約社員", "その他"])),
            rule("入稿ステータス", one_of(["掲載", "非掲載"])),
            rule("給与パターン", one_of([p for p in ("基本", "高額", "低額") if p in bank.salary_patterns] or ["基本"]))]
    for i, (n, vals) in enumerate(lists):
        if vals:
            reqs.append(rule(n, in_list(i, len(vals))))
    reqs += [
        {"repeatCell": {"range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "wrapStrategy": "WRAP",
                                                       "backgroundColor": {"red": 0.87, "green": 0.92, "blue": 0.97}}},
                        "fields": "userEnteredFormat(textFormat,wrapStrategy,backgroundColor)"}},
        {"repeatCell": {"range": cell_range("実行日"), "cell": {"userEnteredFormat": {
            "numberFormat": {"type": "DATE", "pattern": "yyyy/mm/dd"}}}, "fields": "userEnteredFormat.numberFormat"}},
        {"updateSheetProperties": {"properties": {"sheetId": ws.id, "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}},
        {"updateSheetProperties": {"properties": {"sheetId": lst.id, "hidden": True}, "fields": "hidden"}},
    ]
    book.batch_update({"requests": reqs})
    done_list.append(f"プルダウンを付けました（会社 {len(companies)}社・職種 {len(categories)}種類・画像カテゴリー {len(images)}種類・"
                     f"職種名選択 {len(titles)}件。夜勤有無はチェックボックス）")
    return done_list


def _col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def write_result(book, row: int, text: str) -> None:
    """入稿予定表の「実行結果」列に書く。"""
    ws = book.worksheet(SHEET)
    head = [header_name(h) for h in ws.row_values(1)]
    if "実行結果" in head:
        ws.update_cell(row, head.index("実行結果") + 1, text)
