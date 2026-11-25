"""施策の作り方（＜ヒトマネ/施策用＞求人原稿自動生成 に付いている GAS の「③予約リストを一括実行」）を Python に移したもの。

元は施策用ブックの GAS（コード.js の hmGenerateBatchV2_ ほか。2026-11-18 に clasp で読み取りだけした）。
関数ごとに GAS の名前を書いておく。いつもの作り方（generator.py）との違い：

- 土台は ＜土台/施策用＞（BASE_SPREADSHEET_ID）。シートの読み方は generator.build_bank と同じ
- 6重め/7軽めの職種名・仕事内容は ＜ヒトマネ＞重め軽め職種分類 の「6重め_工場系で手のひら_ヒトマネ用」などのシートから、
  「分類」で選んだ範囲を読む（土台の 6重め/7軽め シートは使わない）
- 職種名は勤務地ごとにランダム。同じ会社の同じ勤務地では、一度使った職種名は使わない（会社×勤務地×職種名の使用履歴）
- 職種名指定（空欄=ランダム）、勤務地_都道府県・勤務地_市区町村（空欄=全部）で絞れる
- 画像は3枚（1枚目=画像カテゴリー、2枚目=転職サポート、3枚目=社名入り_<会社名>）
- 募集職種は「急募／職種名／F列の語／H列の語／タイトル末尾ワード」（タイトル編集シートの4行目から。100文字まで）
- お仕事内容の前後に「お仕事内容上」「お仕事内容下」の文を付ける
- 給与パターンに「25万」などが使える（下限を 250000〜259999 からランダム、上限は下限×1.25）
- 旧FMT（109列）も作る

使用履歴は読むだけ（シートには書かない。ツールで入稿したぶんは、このパソコンの記録に残して次から避ける）。
"""
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from . import generator as g
from .headers import NEW_FORMAT, OLD_FORMAT

BASE_SPREADSHEET_ID = "1GVHb8nFdDmbAb8GPX0NYK58QRopGslhnObTTolSuLbY"  # ＜土台/施策用＞（HM_BASE_SPREADSHEET_ID）
BUNRUI_SPREADSHEET_ID = "1zEqxa29LbRbMBV0jPy-O2Yj-6VeiUSOdj54qGGz5jkY"  # ＜ヒトマネ＞重め軽め職種分類
LOC_USAGE_SHEET = "ヒトマネ_会社×勤務地×職種名_使用履歴"
TITLE_SHEET = "タイトル編集"
TITLE_DATA_START_ROW = 4
TITLE_MAX_LENGTH = 100
IMAGE_SUPPORT_COLUMN = "転職サポート"
IMAGE_COMPANY_PREFIX = "社名入り_"
SALARY_UPPER_RATE = 1.25
BUNRUI_SHEET_PARTS = {"重労働": "工場系で重労働", "手のひら": "工場系で手のひら",
                      "そこまで重労働ではない": "工場系でそこまで重労働ではない", "倉庫系": "倉庫系"}
BUNRUI_OPTIONS = ["重労働", "手のひら", "そこまで重労働ではない", "倉庫系", "工場系3つ全部", "4つ全部"]
BUNRUI_CONTENT_COLS = (4, 15)  # D〜O列（P列は使わない）
SALARY_MAN_OPTIONS = [f"{m}万" for m in range(20, 41)]

# 旧FMT の固定列（HITOMANE_FIXED_VALUES。GAS のまま）
OLD_FIXED_VALUES = {
    "媒体": "自社", "応募フォーム": "応募項目パターン１", "シフト": "週5日以上",
    "早朝": "TRUE", "朝": "TRUE", "昼": "TRUE", "夕方": "TRUE", "夜": "TRUE", "深夜": "TRUE",
    "シフト制勤務": "TRUE", "即日勤務OK": "TRUE", "未経験者歓迎": "TRUE", "交通費支給": "TRUE", "寮・社宅あり": "TRUE",
    "制服貸与": "TRUE", "平日のみOK": "TRUE", "フリーター歓迎": "TRUE", "経験者歓迎": "TRUE", "仕事ブランクOK": "TRUE",
    "地図用テキスト": "勤務地はこの周辺です。", "地図用タイトル": "勤務所在地", "担当": "採用担当", "掲載用拠点名": "非公開",
    "雇用形態": "正社員",
}
SMOKING_NOTE = "【受動喫煙対策】受動喫煙対策あり（屋内禁煙）"


@dataclass
class Base:
    """施策用の土台と使用履歴。使用履歴は実行の中で書き足していく（同じ実行の後ろの行が避けるため。シートには書かない）。"""
    bank: g.Bank
    title: dict                                          # head（急募）・f・h（タイトル編集シートの語）
    loc_used: dict = field(default_factory=dict)         # "会社||都道府県||市区町村" → 使った職種名の set
    content_used: dict = field(default_factory=dict)     # "会社||職種番号" → 使った仕事内容の set
    decks: dict = field(default_factory=dict)            # タイトルの語の山札（全部の語を1周するまで同じ語は出さない）
    bunrui_cache: dict = field(default_factory=dict)


def loc_key(company: str, pref: str, city: str) -> str:  # hmLocKey_
    return f"{company}||{pref}||{city}"


def title_words(rows: list[list]) -> dict:
    """タイトル編集シートの4行目からの値（A列から）。B列=先頭の語、F列・H列=ランダムの語。D列とJ列は見本なので読まない。"""
    def words(ci):
        out = []
        for r in rows:
            v = str(r[ci]).strip() if ci < len(r) and r[ci] is not None else ""
            if v and v not in out:
                out.append(v)
        return out
    return {"head": (words(1) or [""])[0], "f": words(5), "h": words(7)}


def from_grids(grids: list[g.Grid], title_rows: list[list], loc_rows=(), content_rows=()) -> Base:
    base = Base(g.build_bank(grids), title_words(title_rows))
    for r in loc_rows:
        r = [("" if c is None else str(c)) for c in r] + [""] * 6
        if r[0] and r[4]:
            base.loc_used.setdefault(loc_key(r[0], r[2], r[3]), set()).add(r[4])
    for r in content_rows:
        r = [("" if c is None else str(c)) for c in r] + [""] * 3
        base.content_used.setdefault(f"{r[0]}||{r[1]}", set()).add(r[2])
    return base


def load_base(book) -> Base:
    """＜土台/施策用＞を読む（読むだけ）。使用履歴・原稿確認用・テンプレのシートは生成に使わないので読まない。"""
    names = [ws.title for ws in book.worksheets()]
    want = [n for n in names if n != TITLE_SHEET and not any(s in n for s in ("使用履歴", "原稿確認用", "テンプレ"))]
    params = {"valueRenderOption": "FORMATTED_VALUE"}
    res = book.values_batch_get([g._quote(n) for n in want], params=params)
    grids = [g.Grid(n, vr.get("values", [])) for n, vr in zip(want, res.get("valueRanges", []))]
    ranges = {TITLE_SHEET: f"{g._quote(TITLE_SHEET)}!A{TITLE_DATA_START_ROW}:H",
              LOC_USAGE_SHEET: f"{g._quote(LOC_USAGE_SHEET)}!A2:F",
              g.CONTENT_USAGE_SHEET_NAME: f"{g._quote(g.CONTENT_USAGE_SHEET_NAME)}!A2:C"}
    have = [n for n in ranges if n in names]
    got = book.values_batch_get([ranges[n] for n in have], params=params).get("valueRanges", []) if have else []
    vals = dict(zip(have, (r.get("values", []) for r in got)))
    return from_grids(grids, vals.get(TITLE_SHEET, []), vals.get(LOC_USAGE_SHEET, []),
                      vals.get(g.CONTENT_USAGE_SHEET_NAME, []))


def remember_local(base: Base, data: dict) -> Base:
    """このパソコンでツールが入稿した分（plan の usage_local.json）を使用履歴に足す。"""
    for r in data.get("locations", []):
        base.loc_used.setdefault(loc_key(r[0], r[2], r[3]), set()).add(r[4])
    for comp, cat, content in data.get("contents", []):
        base.content_used.setdefault(f"{comp}||{cat}", set()).add(content)
    return base


# ---------------------------------------------------------------- 6重め/7軽め（＜ヒトマネ＞重め軽め職種分類）

def bunrui_reader(book):
    """分類のスプレッドシートから、シート1枚（2行目から A〜O列）を読む関数を返す。"""
    names = None

    def read(sheet_name: str) -> list[list]:
        nonlocal names
        if names is None:
            names = [ws.title for ws in book.worksheets()]
        if sheet_name not in names:
            raise g.GenerateError(f"「＜ヒトマネ＞重め軽め職種分類」に「{sheet_name}」シートが見つかりません")
        return book.values_get(f"{g._quote(sheet_name)}!A2:O", params={"valueRenderOption": "FORMATTED_VALUE"}).get(
            "values", [])
    return read


def read_bunrui_sheet(values: list[list]) -> list[dict]:  # hmReadBunruiSheet_
    out = []
    a, b = BUNRUI_CONTENT_COLS
    for r in values:
        r = [("" if c is None else str(c)) for c in r] + [""] * b
        title = r[0].strip()
        contents = [v for v in r[a - 1:b] if v != ""]
        if title and contents:
            out.append({"title": title, "letter": r[1].strip(), "contents": contents})
    return out


def bunrui_pool(heavy_light: str, selection: str, reader, cache: dict) -> list[dict]:  # hmLoadBunruiPool_
    label = g.CATEGORY_NUMBER_LABEL[heavy_light]  # 6重め / 7軽め
    if selection == "工場系3つ全部":
        keys = ["重労働", "手のひら", "そこまで重労働ではない"]
    elif selection == "4つ全部":
        keys = list(BUNRUI_SHEET_PARTS)
    elif selection in BUNRUI_SHEET_PARTS:
        keys = [selection]
    else:
        raise g.GenerateError(f"分類「{selection}」は選択肢にありません（{'・'.join(BUNRUI_OPTIONS)}）")
    if reader is None:
        raise g.GenerateError("＜ヒトマネ＞重め軽め職種分類 を読めません（6重め/7軽めを作るのに使います）")
    seen, pool = set(), []
    for k in keys:
        name = f"{label}_{BUNRUI_SHEET_PARTS[k]}_ヒトマネ用"
        if name not in cache:
            cache[name] = read_bunrui_sheet(reader(name))
        for e in cache[name]:
            if e["title"] not in seen:
                seen.add(e["title"])
                pool.append(e)
    return pool


# ---------------------------------------------------------------- 部品

def _shuffle(arr: list, rnd: random.Random) -> list:  # hmShuffle_
    a = list(arr)
    for i in range(len(a) - 1, 0, -1):
        j = rnd.randrange(i + 1)
        a[i], a[j] = a[j], a[i]
    return a


def draw_word(base: Base, column: str, words: list, employment: str, rnd: random.Random) -> str:  # hmDrawTitleWord_
    """全部の語を1周するまで同じ語は出さない。正社員以外のときは「正社員」の入った語を使わない。"""
    seishain = not employment or employment == "正社員"
    pool = words if seishain else [w for w in words if "正社員" not in w]
    if not pool:
        return ""
    key = column + ("" if seishain else "_正社員以外")
    if not base.decks.get(key):
        base.decks[key] = _shuffle(pool, rnd)
    return base.decks[key].pop()


def composed_title(base: Base, title: str, end_word: str, employment: str, rnd: random.Random) -> str:  # hmBuildComposedTitle_
    tc = base.title
    if not tc["f"] or not tc["h"]:
        raise g.GenerateError(f"「{TITLE_SHEET}」シートのF列・H列に語が入っていません")
    parts = [tc["head"], title, draw_word(base, "F", tc["f"], employment, rnd),
             draw_word(base, "H", tc["h"], employment, rnd), (end_word or "").strip()]
    text = "／".join(p for p in parts if p)
    if len(text) > TITLE_MAX_LENGTH:
        raise g.GenerateError(f"タイトルが{TITLE_MAX_LENGTH}文字を超えました({len(text)}文字): {text}")
    return text


def part_keys(bank: g.Bank, night: str) -> dict:  # hmResolvePartKeys_
    f = lambda *s: g._find_parts_key(bank, *s)
    return {"qual": f("応募資格"), "work_time": f("勤務時間", night) if night else f("勤務時間"), "period": f("勤務期間"),
            "benefit": f("待遇"), "holiday": f("休日"), "apply": f("応募方法"), "pr": f("PR"), "salary_text": f("給与"),
            "top": f("お仕事内容上"), "bottom": f("お仕事内容下")}


def _pick(bank: g.Bank, key: str | None, rnd: random.Random) -> str:
    return rnd.choice(bank.parts[key]) if key and bank.parts.get(key) else ""


def wrap_content(bank: g.Bank, content: str, keys: dict, rnd: random.Random) -> str:  # hmWrapJobContent_
    top = _pick(bank, keys["top"], rnd)
    bottom = _pick(bank, keys["bottom"], rnd)
    return "\n\n".join(x for x in (top, content, bottom) if x)


def salary_picker(bank: g.Bank, pattern: str, count: int, rnd: random.Random):  # hmMakeSalaryPicker_
    """呼ぶたびに1件分の給与 {lower, upper, detail} を返す関数。「25万」なら下限を 250000〜259999 から重ならないように選ぶ。"""
    m = re.fullmatch(r"(\d+)\s*万", str(pattern or "").strip())
    if not m:
        pool = bank.salary_patterns.get(pattern) or bank.salary_patterns.get("基本") or []
        return lambda: rnd.choice(pool) if pool else None
    low_base = int(m.group(1)) * 10000
    offsets = _shuffle(range(10000), rnd)
    templates = []
    for ps in bank.salary_patterns.values():
        for p in ps:
            d = str(p.get("detail") or "")
            if not d or "万円" in d:
                continue
            if len(re.findall(r"\d[\d,，]{4,}", d)) in (1, 2):
                templates.append(d)
    if not templates:
        raise g.GenerateError(f"給与パターン「{pattern}」を使うための給与の文章が、給与シートに見つかりません")
    state = {"i": 0}

    def pick():
        lower = low_base + offsets[state["i"] % 10000]
        state["i"] += 1
        upper = int(lower * SALARY_UPPER_RATE + 0.5)
        nums = iter([str(lower), str(upper)])
        detail = re.sub(r"\d[\d,，]{4,}", lambda mm: next(nums, mm.group(0)), rnd.choice(templates))
        return {"lower": str(lower), "upper": str(upper), "detail": detail}
    return pick


def usable_locations(bank: g.Bank, t: g.Target) -> list[dict]:
    """NG エリアを除いてから、勤務地_都道府県・勤務地_市区町村で絞る。"""
    locs = g.usable_locations(bank, t.company)
    if not locs:
        raise g.GenerateError("使用できる勤務地がありません(NGエリアで全件除外された可能性があります)")
    if t.pref:
        locs = [x for x in locs if x["pref"] == t.pref and (not t.city or x["city"] == t.city)]
        if not locs:
            raise g.GenerateError(f"勤務地「{t.pref}{t.city}」が勤務地シートに無いか、この会社のNGエリアです")
    elif t.city:
        raise g.GenerateError("勤務地_市区町村を選ぶときは、勤務地_都道府県も選んでください")
    return locs


# ---------------------------------------------------------------- 1件分の原稿

def _memo(t: g.Target, company: dict, content_category: str, letter: str, salary, image: str, place: str,
          creation: date) -> str:
    cat_label = g.CATEGORY_NUMBER_LABEL.get(content_category, "")
    m = re.match(r"^\d+", cat_label)
    return "-".join(str(x) for x in (
        g.MEDIA_CODE, f"{creation:%y%m%d}", g.COMMUTE_CODE.get(t.commute, ""),
        g.EMPLOYMENT_CODE.get(t.employment, g.EMPLOYMENT_CODE["正社員"]), (m.group(0) if m else "") + (letter or ""),
        salary["lower"] if salary else "", salary["upper"] if salary else "", image or "", place,
        company.get("求人メモ用会社名") or company.get("会社名") or ""))


def _common(base: Base, row: dict, title: str, content: str, t: g.Target, company: dict, images: list, salary,
            keys: dict, rnd: random.Random) -> None:
    bank = base.bank
    row["募集職種"] = composed_title(base, title, t.title_dedup_word, row["雇用形態"], rnd)
    row["応募方法"] = company.get("応募方法", "") or ""
    row["仕事内容"] = f"{wrap_content(bank, content, keys, rnd)}\n\n{SMOKING_NOTE}"
    imgs = [x for x in images if x]
    if imgs:
        row["画像名一覧用"] = imgs[0]
    for i, img in enumerate(imgs[:5], start=1):
        row[f"画像名{i}"] = img
    row["拠点コード"] = company.get("拠点コード", "") or ""
    row["拠点"] = company.get("拠点", "") or ""
    if "電話" in (company.get("応募方法", "") or ""):
        row["受付電話番号"] = company.get("電話応募番号", "") or ""


def build_new_row(base: Base, title: str, content: str, content_category: str, t: g.Target, company: dict,
                  loc: dict, images: list, salary, creation: date, entry_number: str, letter: str, work: dict,
                  keys: dict, rnd: random.Random) -> list:  # hmBuildRowNewFmt_
    bank = base.bank
    row = {h: g.NEW_FIXED_VALUES.get(h, "") for h in NEW_FORMAT}
    row["募集番号"] = entry_number or ""
    row["ステータス"] = t.status or "掲載"
    row["開始日"] = f"{creation:%Y/%m/%d}"
    row["終了日"] = f"{g.add_one_year(creation):%Y/%m/%d}"
    row["勤務地_都道府県"], row["勤務地_市区町村"] = loc["pref"], loc["city"]
    row["雇用形態"] = t.employment or g.NEW_FIXED_VALUES["雇用形態"]
    _common(base, row, title, content, t, company, images, salary, keys, rnd)
    for col, key in (("PR", "pr"), ("勤務期間", "period"), ("応募資格", "qual"), ("待遇", "benefit"), ("休日・休暇", "holiday")):
        if keys[key]:
            row[col] = _pick(bank, keys[key], rnd)
    apply_text = _pick(bank, keys["apply"], rnd)
    row["応募方法_補足"] = "\n".join(x for x in (apply_text, company.get("応募方法#2", "") or "") if x)
    if salary:
        row["基本給_最低額"], row["基本給_最高額"], row["給与"] = salary["lower"], salary["upper"], salary["detail"]
    for i in (1, 2, 3):
        row[f"勤務時間_開始_{i}"] = work.get(f"start{i}", "")
        row[f"勤務時間_終了_{i}"] = work.get(f"end{i}", "")
        row[f"実働時間_最小_{i}"] = work.get(f"min{i}", "")
        row[f"休憩時間_{i}"] = work.get(f"break{i}", "")
    row["勤務時間_補足"] = work.get("supplement", "")
    place = loc["pref"] + loc["city"]
    row["地図用住所"] = row["勤務地_補足"] = place
    row["お仕事番号"] = _memo(t, company, content_category, letter, salary, images[0] if images else "", place, creation)
    return [row[h] for h in NEW_FORMAT]


def build_old_row(base: Base, title: str, content: str, content_category: str, t: g.Target, company: dict,
                  loc: dict, images: list, salary, creation: date, entry_number: str, letter: str, keys: dict,
                  rnd: random.Random) -> list:  # hmBuildRow_
    bank = base.bank
    row = {h: OLD_FIXED_VALUES.get(h, "") for h in OLD_FORMAT}
    row["募集番号"] = entry_number or ""
    row["ステータス"] = t.status or "掲載"
    row["開始日"] = f"{creation:%Y/%m/%d}"
    row["終了日"] = f"{g.add_one_year(creation):%Y/%m/%d}"
    row["都道府県"], row["市区町村"] = loc["pref"], loc["city"]
    row["雇用形態"] = t.employment or OLD_FIXED_VALUES["雇用形態"]
    _common(base, row, title, content, t, company, images, salary, keys, rnd)
    for col, key in (("PR", "pr"), ("給与", "salary_text"), ("勤務時間", "work_time"), ("勤務期間", "period"),
                     ("応募資格", "qual"), ("待遇", "benefit")):
        if keys[key]:
            row[col] = _pick(bank, keys[key], rnd)
    if keys["holiday"]:
        holiday = _pick(bank, keys["holiday"], rnd)
        row["勤務期間"] = row["勤務期間"] or holiday  # GAS のまま（勤務期間が空のときだけ休日を入れる）
    apply_text = _pick(bank, keys["apply"], rnd)
    apply2 = "\n".join(x for x in (apply_text, company.get("応募方法#2", "") or "") if x)  # 2つ目の「応募方法」列
    row["最低給与額"] = ""
    if salary:
        row["一覧用給与"] = row["給与"] = salary["detail"]
    place = loc["pref"] + loc["city"]
    row["勤務地"] = row["地図用住所"] = place
    row["お仕事番号"] = _memo(t, company, content_category, letter, salary, images[0] if images else "", place, creation)
    out, seen = [], {}
    for h in OLD_FORMAT:  # hmRowToArray_（同じ見出しの2つ目は apply2）
        seen[h] = seen.get(h, 0) + 1
        out.append(apply2 if h == "応募方法" and seen[h] >= 2 else row.get(h, ""))
    return out


# ---------------------------------------------------------------- 1行分の予約

@dataclass
class Batch:
    rows: list
    title_counts: dict
    content_counts: dict
    loc_records: list
    entry_no_end: str


def generate_batch(base: Base, t: g.Target, entry_prefix: str, reader, rnd: random.Random, now: datetime,
                   today: date, work_guard=None) -> Batch:  # hmGenerateBatchV2_
    bank = base.bank
    content_category = g._content_category(t.category)
    heavy_light = content_category if content_category in ("重め", "軽め") else ""

    # 職種名の候補
    contents_pool = []
    if heavy_light:
        if not t.bunrui:
            raise g.GenerateError(f"カテゴリ「{t.category}」は「分類」の選択が必須です")
        pool = bunrui_pool(heavy_light, t.bunrui, reader, base.bunrui_cache)
        if not pool:
            raise g.GenerateError(f"分類「{t.bunrui}」の職種名が見つかりません(＜ヒトマネ＞重め軽め職種分類 の _ヒトマネ用 シートを確認してください)")
    else:
        titles = bank.job_titles.get(t.category) or []
        if not titles:
            raise g.GenerateError(f"カテゴリ「{t.category}」の職種名が見つかりません")
        contents_pool = bank.job_contents.get(content_category) or []
        if not contents_pool:
            raise g.GenerateError(f"カテゴリ「{content_category}」の仕事内容が見つかりません")
        pool, seen = [], set()
        for x in titles:
            x = str(x).strip()
            if x and x not in seen:
                seen.add(x)
                pool.append({"title": x, "letter": "", "contents": None})

    # 職種名の指定（空欄ならランダム）
    spec = None
    if t.title_spec:
        name = t.title_spec.split("｜", 1)[1].strip() if "｜" in t.title_spec else t.title_spec.strip()
        spec = next((e for e in pool if e["title"] == name), None)
        if spec is None and heavy_light:  # 選んだ分類以外のシートの職種名も指定できる
            spec = next((e for e in bunrui_pool(heavy_light, "4つ全部", reader, base.bunrui_cache) if e["title"] == name),
                        None)
        if spec is None:
            if heavy_light:
                raise g.GenerateError(f"職種名「{name}」が＜ヒトマネ＞重め軽め職種分類に見つかりません")
            spec = {"title": name, "letter": "", "contents": None}

    company = bank.companies.get(t.company)
    if company is None:
        raise g.GenerateError(f"会社「{t.company}」が会社情報マスターに見つかりません")
    locations = usable_locations(bank, t)
    count = len(locations) if t.count is None else int(t.count)

    # 勤務地ごとの件数（原稿数を勤務地に均等に配る。勤務地数より少なければ、ランダムに選んだ勤務地に1件ずつ）
    shuffled = _shuffle(locations, rnd)
    n = len(shuffled)
    plan = [{"loc": loc, "count": count // n + (1 if i < count % n else 0)} for i, loc in enumerate(shuffled)]
    plan = [p for p in plan if p["count"] > 0]

    # 勤務地ごとに職種名を決める（会社×勤務地で使用済みの職種名は使わない）
    problems = []
    for p in plan:
        place = p["loc"]["pref"] + p["loc"]["city"]
        used = base.loc_used.get(loc_key(t.company, p["loc"]["pref"], p["loc"]["city"]), set())
        if spec:
            if spec["title"] in used:
                problems.append(f"{place}(「{spec['title']}」は使用済み)")
                continue
            if p["count"] > 1:
                problems.append(f"{place}(職種名を指定した場合、1つの勤務地に作れるのは1件です。この勤務地は{p['count']}件)")
                continue
            p["entries"] = [spec]
        else:
            cands = [e for e in pool if e["title"] not in used]
            if len(cands) < p["count"]:
                problems.append(f"{place}({p['count']}件必要／未使用の職種名は残り{len(cands)}件・"
                                f"{p['count'] - len(cands)}件不足)")
                continue
            p["entries"] = _shuffle(cands, rnd)[:p["count"]]
    if problems:
        more = f" ほか{len(problems) - 10}件" if len(problems) > 10 else ""
        raise g.GenerateError(f"同じ会社×勤務地で、職種名が足りない／使用済みです: {'、'.join(problems[:10])}{more}")

    # 画像（1枚目=画像カテゴリー、2枚目=転職サポート、3枚目=社名入り）
    image_key = (t.image_category or bank.image_category_by_job_category.get(content_category)
                 or next((k for k in bank.images_by_category if content_category and content_category in k), None)
                 or next(iter(bank.images_by_category), None))
    images = bank.images_by_category.get(image_key) or []
    support = bank.images_by_category.get(IMAGE_SUPPORT_COLUMN) or []
    if not support:
        raise g.GenerateError(f"土台の「画像」シートに「{IMAGE_SUPPORT_COLUMN}」列が無いか、画像名が入っていません")
    company_key = IMAGE_COMPANY_PREFIX + t.company
    company_images = bank.images_by_category.get(company_key) or []
    if not company_images:
        raise g.GenerateError(f"土台の「画像」シートに「{company_key}」列が無いか、画像名が入っていません")

    salary = salary_picker(bank, t.salary_pattern, count, rnd)
    keys = part_keys(bank, t.night_shift)
    is_new = t.format == "新FMT"
    work_pool = []
    if is_new:
        work_pool = (bank.work_time_by_shift.get(t.night_shift) if t.night_shift and bank.work_time_by_shift.get(t.night_shift)
                     else bank.work_time_patterns)
        if not work_pool:
            raise g.GenerateError("「勤務時間」シート(新FMT用の勤務時間パターン。夜勤あり/なし別、または従来型)が見つかりません")

    headers = NEW_FORMAT if is_new else OLD_FORMAT
    number = g._entry_numbers(entry_prefix)
    creation = g.parse_creation_date(t.creation_date, today)
    used_contents = base.content_used.get(f"{t.company}||{t.category}", set())
    stamp = f"{now:%Y-%m-%d %H:%M}"
    rows, title_counts, content_counts, loc_records, offset = [], {}, {}, [], 0
    for p in plan:
        for e in p["entries"]:
            cpool = e["contents"] or contents_pool
            unused = [c for c in cpool if c not in used_contents]  # hmPickUnusedContent_
            content = rnd.choice(unused or cpool)
            code = number(offset)

            def make(p=p, e=e, content=content, code=code):  # 選び直すたびに画像・給与（と勤務時間）を引き直す
                imgs = [rnd.choice(images) if images else "", rnd.choice(support), rnd.choice(company_images)]
                sal = salary()
                if is_new:
                    r = build_new_row(base, e["title"], content, content_category, t, company, p["loc"], imgs, sal,
                                      creation, code, e["letter"], rnd.choice(work_pool), keys, rnd)
                else:
                    r = build_old_row(base, e["title"], content, content_category, t, company, p["loc"], imgs, sal,
                                      creation, code, e["letter"], keys, rnd)
                return r, r[headers.index("お仕事番号")]
            rows.append(work_guard.pick(make, code) if work_guard is not None else make()[0])
            title_counts[e["title"]] = title_counts.get(e["title"], 0) + 1
            content_counts[content] = content_counts.get(content, 0) + 1
            loc_records.append([t.company, t.category, p["loc"]["pref"], p["loc"]["city"], e["title"], stamp])
            offset += 1
    return Batch(rows, title_counts, content_counts, loc_records, number(offset))


def output_name(first: g.Target, today: date) -> str:
    created = g.parse_creation_date(first.creation_date, today)
    label = "" if first.group_id.startswith("_単独_") else f"G{first.group_id}_"
    new = "新_" if first.format == "新FMT" else ""
    return f"ヒトマネ出力_施策_{new}{label}{first.company}_{first.category}_{created:%Y%m%d}"[:95]


def run(base: Base, targets: list[g.Target], reader=None, seed=None, now: datetime | None = None,
        today: date | None = None, continuation: dict | None = None, guard=None) -> list[g.GroupResult]:
    """予約行を順に作る（hmRunFromConfig の生成部分）。エラーの行は、そのグループだけ作らずに続ける。

    募集番号の先頭が空の行は、同じ会社の前の行の続きの番号を使う（continuation：会社 → 次の募集番号。渡せば書き足す）。
    うまく作れた行の職種名・仕事内容は base の使用履歴に足す（同じ実行の後ろの行が避けるため。シートには書かない）。
    guard（work_numbers.Guard）を渡すと、同じ日のお仕事番号と重ならないように画像（1枚目）・給与を選び直す。
    """
    now = now or datetime.now()
    today = today or now.date()
    rnd = random.Random(seed)
    continuation = {} if continuation is None else continuation
    results = []
    for gid, ts in g.groups_of(targets).items():
        first = ts[0]
        res = g.GroupResult(gid, output_name(first, today), first.company, first.category, ts,
                            headers=NEW_FORMAT if first.format == "新FMT" else OLD_FORMAT)
        batches = []
        try:
            for t in ts:
                where = f"行{t.sheet_row}: "
                if t.format != first.format:
                    raise g.GenerateError(where + "同じグループの中で、フォーマット(旧FMT/新FMT)が混ざっています")
                if t.format not in ("新FMT", "旧FMT"):
                    raise g.GenerateError(where + f"フォーマット「{t.format}」は 旧FMT か 新FMT にしてください")
                if not t.category:
                    raise g.GenerateError(where + "職種番号(カテゴリ)が空です")
                if not t.entry_prefix and not continuation.get(t.company):
                    raise g.GenerateError(where + "募集番号の先頭が空です(この会社で最初の予約行は必須入力です)")
                if not t.image_category:
                    raise g.GenerateError(where + "画像カテゴリーが空です(必須入力です)")
                if not t.company:
                    raise g.GenerateError(where + "会社名が空です")
                if t.count is not None and (t.count != t.count or t.count <= 0):
                    raise g.GenerateError(where + "原稿数が数値になっていません")
                try:
                    b = generate_batch(base, t, t.entry_prefix or continuation[t.company], reader, rnd, now, today,
                                       guard)
                except g.GenerateError as e:
                    raise g.GenerateError(where + str(e)) from None
                continuation[t.company] = b.entry_no_end
                batches.append((t, b))
                # 同じ実行の後ろの行が、同じ会社×勤務地×職種名を使わないように（GAS と同じく作ったらすぐ足す）
                for rec in b.loc_records:
                    base.loc_used.setdefault(loc_key(rec[0], rec[2], rec[3]), set()).add(rec[4])
                base.content_used.setdefault(f"{t.company}||{t.category}", set()).update(b.content_counts)
        except g.GenerateError as e:
            res.error = str(e)
            results.append(res)
            continue
        for t, b in batches:
            res.rows.extend(b.rows)
            res.title_counts.append(b.title_counts)
            res.content_counts.append(b.content_counts)
            res.loc_records.extend(b.loc_records)
        results.append(res)
    return results
