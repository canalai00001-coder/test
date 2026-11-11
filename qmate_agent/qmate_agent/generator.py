"""原稿の生成（GAS の「③予約リストを一括実行」と同じ処理を Python で行う）。

通勤用・入寮用それぞれの GAS（Code.gs）の buildContentBank_・generateBatch_・buildRow_・buildMemo_ をそのまま移した。
入寮用は bank.dorm が True のときの処理（時給・入寮タイトル・スタンバイタイトル・お仕事内容の上など）。
土台のスプレッドシート（職種名・会社情報・給与・勤務地・タイトル・パーツ・画像・仕事内容・テンプレート）と、
本体のスプレッドシートのテンプレート(固定列)を読み、予約1行分の原稿を作る。
シートの役割は GAS と同じく、タブ名と中身（見出し）から判定する。
"""
import random
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .checks import is_sheet_error
from .qmate_headers import QMATE_HEADERS

CATEGORY_NAMES = ["クルマ", "工場", "軽作業", "電子部品", "半導体", "重め", "軽め", "梱包", "検査", "ピッキング",
                  "仕分け", "シール貼り"]
CATEGORY_NUMBER_LABEL = {c: f"{i}{c}" for i, c in enumerate(CATEGORY_NAMES, start=1)}
QMATE_CATEGORY = ["製造・生産工程従事者", "工作機械・機械オペレーター・溶接工", "その他"]
STANDBY_KEYWORDS_BY_CATEGORY = {
    "クルマ": ["挑戦するなら今", "高収入寮付", "ガッツリ稼ぐ", "覚えやすい"],
    "工場": ["寮即入OK", "稼げる工場"],
    "軽作業": ["住込みOK", "なし", "急募案件", "急募採用"],
    "半導体": ["住込みOK", "ガッツリ稼ぐ", "急募採用", "覚えやすい"],
    "梱包": ["月収35万以上", "軽作業募集", "工場ワーク", "即日入社", "急募採用"],
    "検査": ["覚えやすい", "高収入", "構内作業"],
    "シール貼り": ["稼げる工場", "即勤務可", "工場内作業", "月収安定", "工場勤務"],
}
STANDBY_KEYWORDS_FALLBACK = ["急募採用", "高収入", "未経験OK", "覚えやすい"]
TITLE_MEASURE_2_PHRASES = ["年間休日120日", "交通費支給", "20代・30代活躍"]
TITLE_MAX_BENEFIT_WORDS = 3
TITLE_LIMIT = 50
COOLDOWN_DAYS = 30
COMMUTE_CODE = {"通勤": 1, "入寮": 2}
EMPLOYMENT_CODE = {"正社員（人材紹介）": 1, "契約社員（人材紹介）": 2, "その他": 3}
NIGHT_VARIANT_MARKER = "2時"
USAGE_SHEET = "アカウント×職種名_使用履歴"

# 原稿の材料ではないので読まないシート（GAS の buildContentBank_ と同じもの＋このツールが作ったシート）
SKIP_EXACT = {"マニュアル", "スタンバイタイトル", "実行設定", USAGE_SHEET, "_プルダウン用リスト（自動生成・編集不要）",
              "検品シート", "入稿予定表", "取り下げ予定表", "AIチェック結果",
              "Q-mateログイン情報"}
# 「【ArK_製造】応募資格・…」のような会社専用のシートは、まだ使わない（使うと、ほかの会社の原稿にも文例が混ざる）
SKIP_PREFIX = ("原稿確認", "出力_", "_tmp_出力_", "_入稿予定表_候補", "【")
SKIP_CONTAINS = ("入稿原稿", "原稿検討シート", "記録用", "使用履歴")
# 入寮用：時給データの「月収例」の表記（入寮用 GAS の MONTHLY_EXAMPLE_LABEL_OPTIONS）
MONTHLY_EXAMPLE_LABELS = ["【月収例】", "＜月収例＞", "〈月収例〉", "◎月収例◎", "【月収イメージ】", "＜月収イメージ＞", "〈月収イメージ〉",
                          "【想定月収】", "＜想定月収＞", "〈想定月収〉", "【月収目安】", "＜月収目安＞", "〈月収目安〉"]
HOURS_PER_DAY, DAYS_PER_MONTH = 8, 22


def text(v) -> str:
    """GAS の String(v) と同じ見え方にする（スプレッドシートの整数は 250000.0 ではなく 250000）。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def js_round(x: float) -> int:
    """JavaScript の Math.round（.5 は切り上げ）。Python の round は .5 を偶数に寄せるので、給与の上限が1円ずれる。"""
    import math
    return math.floor(x + 0.5)


def js_len(s: str) -> int:
    """JavaScript の文字数（UTF-16）。T列の50文字の判定を GAS と同じにする。"""
    return len(s.encode("utf-16-le")) // 2


def norm_header(s) -> str:
    return re.sub(r"[\s　]+", "", unicodedata.normalize("NFKC", text(s)))


# ---------------------------------------------------------------- 土台の読み込み
@dataclass
class Bank:
    job_titles: dict = field(default_factory=dict)       # {'1クルマ': [...]}
    job_contents: dict = field(default_factory=dict)     # {'クルマ': [...]}
    parts: dict = field(default_factory=dict)            # {'キャッチコピー': [...], ...}（見出しの順）
    companies: dict = field(default_factory=dict)
    locations: list = field(default_factory=list)        # [(都道府県, 市区町村)]
    ng_by_company: dict = field(default_factory=dict)
    fixed_template: dict = field(default_factory=dict)
    images_by_category: dict = field(default_factory=dict)
    image_category_by_job: dict = field(default_factory=dict)
    salary_patterns: dict = field(default_factory=dict)  # {'基本': [{'lower','upper','detail'}]}
    salary_detail_templates: list = field(default_factory=list)
    standby_keywords: dict = field(default_factory=dict)
    personas: list = field(default_factory=list)
    appeals: list = field(default_factory=list)
    keyword_pool: list = field(default_factory=list)
    dedup_word: str = ""
    measure2: dict = field(default_factory=lambda: {"fixed1": [], "benefit": [], "fixed2": []})
    paired: dict = field(default_factory=dict)           # {'重め': [{'title','letter','contents'}]}
    dorm: bool = False                                   # 入寮用の土台
    standby_titles: list = field(default_factory=list)   # 入寮用：スタンバイタイトルシートのA列（S列のキーワード）
    nyuryo_titles: list = field(default_factory=list)    # 入寮用：入寮タイトルシート（T列の部品）
    hourly: list = field(default_factory=list)           # 入寮用：給与（時給）シート [{'lower','upper','template'}]
    error_cells: dict = field(default_factory=dict)      # {シート名: #REF! などのエラー値だったセルの数}（文例には使わない）


def skip_sheet(name: str, dorm: bool = False) -> bool:
    n = name.strip()
    if dorm and n == "スタンバイタイトル":
        return False  # 入寮用では S列のキーワードの一覧として使う
    return n in SKIP_EXACT or n.startswith(SKIP_PREFIX) or any(s in n for s in SKIP_CONTAINS)


def header_row_guess(values) -> int:
    """先頭6行×30列のうち、いちばん埋まっている行（0始まり）。"""
    best, best_count = 0, -1
    for r, row in enumerate(values[:6]):
        count = sum(1 for v in row[:30] if text(v) != "")
        if count > best_count:
            best, best_count = r, count
    return best


def signature_row(values, needles) -> int:
    for r, row in enumerate(values[:6]):
        joined = " ".join(text(v) for v in row[:30])
        if all(n in joined for n in needles):
            return r
    return header_row_guess(values)


def qmate_header_row(values) -> int:
    for r, row in enumerate(values[:6]):
        if sum(1 for v in row[:260] if text(v) in QMATE_HEADERS) >= 50:
            return r
    return -1


def standby_header_row(values) -> int:
    for r, row in enumerate(values[:20]):
        if sum(1 for v in row if text(v) == "全応募数") >= 2:
            return r
    return -1


def classify(name: str, values, dorm: bool = False) -> str:
    """GAS の classifySheet_ と同じ順番で、シートの役割を決める（dorm なら入寮用 GAS の判定）。"""
    n = name.strip()
    if n == "スタンバイキーワード(自動集計)":
        return "standby_auto"
    if dorm:
        if n == "スタンバイタイトル":
            return "standby_titles"
        if n == "入寮タイトル":
            return "nyuryo_titles"
        if "時給" in n:
            return "hourly"
    elif n == "タイトル(施策)":
        return "measure2"
    m = re.fullmatch(r"\d+(重め|軽め)", name)
    if m:
        return f"paired:{m.group(1)}"
    m = re.fullmatch(r"\d+(.+)", name)
    if m and m.group(1) in CATEGORY_NAMES:
        return f"content:{m.group(1)}"
    cat = next((c for c in CATEGORY_NAMES if name == c or c in name), None)
    if cat:
        return f"content:{cat}"
    if standby_header_row(values) >= 0:
        return "standby_raw"
    if "テンプレート" in name and qmate_header_row(values) >= 0:
        return "template"
    if qmate_header_row(values) >= 0:
        return "unknown"
    top = " ".join(" ".join(text(v) for v in row[:30]) for row in values[:6])
    if "スタンバイタイトル" in top:
        return "title_parts"
    if "低額" in top and "基本" in top and "高額" in top:
        return "salary"
    if "画像カテゴリー" in top:
        return "images"
    if "都道府県" in top and "市区町村" in top:
        return "locations"
    if "会社名" in top and "応募時メール送信先1" in top:
        return "companies"
    if "キャッチコピー" in top and "応募資格" in top:
        return "parts"
    if values:
        h = header_row_guess(values)
        if sum(1 for v in values[h][:30] if re.match(r"^\d+\S", text(v))) >= 3:
            return "job_titles"
    return "unknown"


def name_role(name: str) -> str | None:
    """中身を読まなくても役割が分かるシート（読み込みを省くため）。"""
    m = re.fullmatch(r"\d+(重め|軽め)", name)
    if m:
        return f"paired:{m.group(1)}"
    m = re.fullmatch(r"\d+(.+)", name)
    if m and m.group(1) in CATEGORY_NAMES:
        return f"content:{m.group(1)}"
    return None


def load_bank(sheets, needed_categories=None, dorm: bool = False) -> Bank:
    """sheets は [(シート名, 値を返す関数)]。土台 → 本体の順に渡す（テンプレートは後の値が勝つ）。

    needed_categories：読み込む仕事内容のカテゴリ（'クルマ' など）。None なら全部。
    dorm：入寮用の土台として読む。
    """
    bank = Bank(dorm=dorm)
    seen_locations = None if dorm else set()  # 入寮用 GAS は勤務地の重複をまとめない
    for name, get in sheets:
        if skip_sheet(name, dorm):
            continue
        role = name_role(name)
        if role and needed_categories is not None and role.split(":")[1] not in needed_categories:
            continue
        values = get()
        if not values:
            continue
        # IMPORTRANGE が読めないときの #REF! などは、文例として使わない（空欄として扱う）
        bad = sum(1 for row in values for v in row if is_sheet_error(v))
        if bad:
            bank.error_cells[name] = bad
            values = [["" if is_sheet_error(v) else v for v in row] for row in values]
        role = classify(name, values, dorm)
        if needed_categories is not None and role.startswith(("content:", "paired:")) \
                and role.split(":")[1] not in needed_categories:
            continue
        _read_role(bank, role, values, seen_locations)
    return bank


def _cell(row, i):
    return row[i] if i < len(row) else ""


def _num(v):
    """JavaScript の Number(v) で数になるものだけ数にする（空欄・文字は None）。"""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _read_role(bank: Bank, role: str, values, seen_locations) -> None:
    if role == "hourly":
        for row in values[1:]:
            lower, upper = _num(_cell(row, 4)), _num(_cell(row, 7))
            if lower is None or upper is None:
                continue
            bank.hourly.append({"lower": js_round(lower), "upper": js_round(upper), "template": text(_cell(row, 9))})
        return
    if role == "nyuryo_titles":
        for row in values[1:]:
            k1, k2 = text(_cell(row, 1)), text(_cell(row, 6))
            if k1 in ("", "0") and k2 in ("", "0"):
                continue
            bank.nyuryo_titles.append({"title": text(_cell(row, 2)).strip(), "night": text(_cell(row, 4)).strip(),
                                       "keyword1": k1, "keyword2": k2, "dedup": text(_cell(row, 8))})
        return
    if role == "standby_titles":
        bank.standby_titles.extend(text(_cell(r, 0)).strip() for r in values if text(_cell(r, 0)) != "")
        return
    if role == "measure2":
        fixed, benefit_col = [], -1
        for row in values[:6]:
            for c, v in enumerate(row[:40]):
                n = re.sub(r"[\s　]", "", unicodedata.normalize("NFKC", text(v)))
                m = re.fullmatch(r"固定([12])?", n)
                if m and all(f[0] != c for f in fixed):
                    fixed.append((c, int(m.group(1)) if m.group(1) else 0))
                elif n.startswith("待遇") and benefit_col < 0:
                    benefit_col = c
        fixed.sort()
        col1 = next((c for c, k in fixed if k == 1), -1)
        col2 = next((c for c, k in fixed if k == 2), -1)
        for c, k in fixed:
            if k:
                continue
            if col1 < 0:
                col1 = c
            elif col2 < 0 and c != col1:
                col2 = c
        cols = [col1 if col1 >= 0 else 6, benefit_col if benefit_col >= 0 else 8, col2 if col2 >= 0 else 10]
        lists = [[], [], []]
        for row in values:
            if not re.fullmatch(r"\d+", text(_cell(row, 0)).strip()):
                continue
            for i, c in enumerate(cols):
                v = text(_cell(row, c)).strip()
                if v and v not in lists[i]:
                    lists[i].append(v)
        bank.measure2 = {"fixed1": lists[0], "benefit": lists[1], "fixed2": lists[2]}
    elif role == "title_parts":
        for row in values:
            if not re.fullmatch(r"\d+", text(_cell(row, 0))):
                continue
            kw, persona, appeal, dedup = (text(_cell(row, i)) for i in (1, 4, 9, 11))
            kw = re.sub(r"＞$", "", re.sub(r"^＜", "", kw)).strip()
            if kw and kw not in bank.keyword_pool:
                bank.keyword_pool.append(kw)
            if persona and persona not in bank.personas:
                bank.personas.append(persona)
            if appeal and appeal not in bank.appeals:
                bank.appeals.append(appeal)
            if dedup:
                bank.dedup_word = dedup
    elif role == "salary":
        for block, start in (("低額", 0), ("基本", 7), ("高額", 14)):
            items = []
            for row in values[3:]:
                lower = _cell(row, start)
                if text(lower) == "":
                    continue
                upper = _cell(row, start + 3)
                items.append({"lower": str(js_round(float(lower))),
                              "upper": "" if text(upper) == "" else str(js_round(float(upper))),
                              "detail": text(_cell(row, start + 5))})
            if items:
                bank.salary_patterns[block] = items
        for row in values:
            t = text(_cell(row, 21))
            if t and "万円" not in t and len(re.findall(r"(?<!万)[\s　]*円", t)) == 2:
                bank.salary_detail_templates.append(t)
    elif role == "standby_auto":
        reverse = {v: k for k, v in CATEGORY_NUMBER_LABEL.items()}
        for row in values[1:]:
            label, rank, kw = text(_cell(row, 0)), text(_cell(row, 1)), text(_cell(row, 2))
            if not label or not kw or rank == "-":
                continue
            bank.standby_keywords.setdefault(reverse.get(label, label), []).append(kw)
    elif role == "images":
        h = signature_row(values, ["画像カテゴリー"])
        headers = values[h]
        mapping = values[h + 1] if h + 1 < len(values) else []
        is_mapping = "職種" in text(_cell(mapping, 0))
        data = values[h + (2 if is_mapping else 1):]
        for c, head in enumerate(headers):
            key = text(head)
            if not key or key == "画像カテゴリー":
                continue
            items = [text(_cell(r, c)) for r in data if text(_cell(r, c)) != ""]
            if items:
                bank.images_by_category[key] = items
            if is_mapping:
                for jc in re.split(r"[・\s]+", text(_cell(mapping, c))):
                    if jc.strip() in CATEGORY_NAMES:
                        bank.image_category_by_job[jc.strip()] = key
    elif role == "template":
        h = qmate_header_row(values)
        value_row = next((r for r in values[h + 1:] if any(text(v) != "" for v in r)), None)
        if value_row is not None:
            for c, head in enumerate(values[h]):
                key, val = text(head), _cell(value_row, c)
                if not key or text(val) == "":
                    continue
                if key in ("給与_下限", "給与_上限", "基本給|▲必須") and isinstance(val, (int, float)):
                    val = js_round(val)
                bank.fixed_template[key] = text(val)
    elif role == "job_titles":
        h = header_row_guess(values)
        for c, head in enumerate(values[h]):
            if re.match(r"^\d+\S", text(head)):
                bank.job_titles[text(head)] = [text(_cell(r, c)) for r in values[h + 1:] if text(_cell(r, c)) != ""]
    elif role.startswith("paired:"):
        cat = role.split(":")[1]
        h = signature_row(values, ["職種名"])
        entries = bank.paired.setdefault(cat, [])
        for row in values[h + 1:]:
            title = text(_cell(row, 0))
            if not title:
                continue
            entries.append({"title": title, "letter": text(_cell(row, 1)).strip(),
                            "contents": [text(v) for v in row[3:] if text(v) != ""]})
    elif role.startswith("content:"):
        cat = role.split(":")[1]
        pool = bank.job_contents.setdefault(cat, [])
        for row in values[1:]:
            pool.extend(text(v) for v in row if text(v) != "")
    elif role == "parts":
        h = signature_row(values, ["キャッチコピー", "応募資格"])
        headers = [text(v) for v in values[h]]
        start = h + 1
        note = re.compile(r"文字まで|文字以内|作成する上の注意点" if bank.dorm else r"文字まで|文字以内")
        if start < len(values) and any(note.search(text(v)) for v in values[start]):
            start += 1
        last_col = {k: c for c, k in enumerate(headers) if k}
        for c, key in enumerate(headers):
            if not key:
                continue
            if "待遇" in key and last_col[key] != c and not bank.dorm:  # 入寮用 GAS は同じ見出しの列をまとめて使う
                continue  # 待遇・福利厚生(正社員) は同じ見出しの一番右の列だけ使う
            pool = bank.parts.setdefault(key, [])
            pool.extend(text(_cell(r, c)) for r in values[start:]
                        if text(_cell(r, c)) != "" and not note.search(text(_cell(r, c))))
    elif role == "companies":
        h = signature_row(values, ["会社名", "応募時メール送信先1"])
        headers = [text(v) for v in values[h]]
        if "会社名" not in headers:
            return
        ci = headers.index("会社名")
        for row in values[h + 1:]:
            name = text(_cell(row, ci))
            if name:
                bank.companies[name] = {k: text(_cell(row, i)) for i, k in enumerate(headers)}
    elif role == "locations":
        h = signature_row(values, ["都道府県", "市区町村"])
        headers = [text(v) for v in values[h]]
        if "都道府県" not in headers or "市区町村" not in headers:
            return
        pi, ci = headers.index("都道府県"), headers.index("市区町村")
        data = values[h + 1:]
        for row in data:
            pref, city = text(_cell(row, pi)), text(_cell(row, ci))
            if not pref:
                continue
            if seen_locations is None:
                bank.locations.append((pref, city))
            elif (pref.strip(), city.strip()) not in seen_locations:
                seen_locations.add((pref.strip(), city.strip()))
                bank.locations.append((pref, city))
        for c, key in enumerate(headers):
            if not key or key in ("都道府県", "市区町村") or "合体" in key:
                continue
            ngs = [text(_cell(r, c)) for r in data if text(_cell(r, c)) != ""]
            if ngs:
                bank.ng_by_company[key] = ngs


# ---------------------------------------------------------------- 使用履歴（30日ルール）
def parse_usage_date(v) -> datetime:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return datetime(1899, 12, 30) + timedelta(days=float(v))
    s = text(v).strip().replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y/%m/%dT%H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return datetime(1970, 1, 1)


def last_used(usage_rows, company: str, category: str) -> dict:
    out = {}
    for r in usage_rows:
        if len(r) >= 6 and text(r[0]) == company and text(r[1]) == category and text(r[5]):
            out[text(r[2])] = parse_usage_date(r[5])
    return out


def update_usage(usage_rows: list, company: str, category: str, counts: dict, now: datetime) -> list:
    """GAS の updateUsageTable_ と同じ更新をした表（見出しを除く8列）を返す。"""
    rows = [list(r[:8]) + [""] * (8 - len(r[:8])) for r in usage_rows]
    index = {(text(r[0]), text(r[1]), text(r[2])): i for i, r in enumerate(rows)}
    stamp = now.strftime("%Y-%m-%d %H:%M")
    for title, count in counts.items():
        i = index.get((company, category, title))
        if i is None:
            rows.append([company, category, title, 1, count, stamp, count, count])
            index[(company, category, title)] = len(rows) - 1
        else:
            r = rows[i]
            r[3] = (float(r[3]) if text(r[3]) else 0) + 1
            r[4] = (float(r[4]) if text(r[4]) else 0) + count
            r[5], r[6], r[7] = stamp, count, count
    return rows


# ---------------------------------------------------------------- 生成
@dataclass
class Request:
    """実行設定の予約1行分。"""
    category: str          # '1クルマ'
    company: str
    count: int | None      # None なら勤務地の数
    commute: str = "通勤"
    employment: str = "正社員（人材紹介）"
    update_type: str = "登録"
    status: str = "公開"
    image_category: str = ""
    salary_pattern: str = ""
    night: str = ""        # '夜勤あり' / '夜勤なし' / '夜勤あり(2時3時)'
    standby_keyword: str = ""
    title_measure: str = ""
    box_word: str = ""     # 求人ボックスワード（重複対策ワード）
    title_choice: str = "" # 6重め/7軽めの職種名選択
    created: date | None = None
    salary_rule: dict | None = None  # 給与設定シートの行（salary.parse の1件）。あれば給与パターンより優先


@dataclass
class Result:
    rows: list
    title_counts: dict
    warnings: list


def is_night(night: str) -> bool:
    return "夜勤あり" in (night or "")


def title_measure_kind(v: str) -> int:
    n = re.sub(r"[\s　]", "", unicodedata.normalize("NFKC", v or ""))
    if not n:
        return 1
    if re.search(r"(タイトル|施策)2", n):
        return 2
    if re.search(r"(タイトル|施策)1", n) or "従来" in n:
        return 1
    return 0


def find_parts_key(bank: Bank, sub: str):
    return next((k for k in bank.parts if sub in k), None)


def find_work_time_key(bank: Bank, night: str):
    keys = list(bank.parts)
    if not night:
        return next((k for k in keys if "勤務時間" in k), None)
    if "夜勤なし" in night:
        return next((k for k in keys if "勤務時間" in k and "夜勤なし" in k), None)
    night_keys = [k for k in keys if "勤務時間" in k and "夜勤あり" in k]
    want = NIGHT_VARIANT_MARKER in night
    return next((k for k in night_keys if (NIGHT_VARIANT_MARKER in k) == want), night_keys[0] if night_keys else None)


def find_work_time_key_dorm(bank: Bank, night: str):
    """入寮用 GAS の findWorkTimeKey_（見出しの全角・改行を正規化し、中身が空の列は選ばない）。"""
    ns = norm_header(night)
    has = lambda k: len(bank.parts.get(k) or []) > 0
    keys = [k for k in bank.parts if "勤務時間" in norm_header(k)]
    if not ns:
        return next((k for k in keys if has(k)), keys[0] if keys else None)
    if "夜勤なし" in ns:
        return next((k for k in keys if "夜勤なし" in norm_header(k) and has(k)), None)
    night_keys = [k for k in keys if "夜勤あり" in norm_header(k) and has(k)]
    want = NIGHT_VARIANT_MARKER in ns
    matched = next((k for k in night_keys if (NIGHT_VARIANT_MARKER in norm_header(k)) == want), None)
    if matched or want:
        return matched
    return night_keys[0] if night_keys else None


def _fill(template: str, nums: list) -> str:
    """「月給　円‐　円」の、円の前の空欄に下限・上限を順に入れる（GAS の fillSalaryTemplate_）。"""
    out, idx, pos = [], 0, 0
    for m in re.finditer(r"(?<!万)[\s　]*円", template):
        out.append(template[pos:m.start()])
        if idx < len(nums):
            out.append(nums[idx] + "円")
            idx += 1
        else:
            out.append(m.group(0))
        pos = m.end()
    out.append(template[pos:])
    return "".join(out)


class Generator:
    def __init__(self, bank: Bank, usage_rows: list, rng: random.Random | None = None, now: datetime | None = None):
        self.bank, self.usage_rows = bank, usage_rows
        self.rng = rng or random.Random()
        self.now = now or datetime.now()
        self.location_queues: dict = {}

    def pick(self, items):
        return items[int(self.rng.random() * len(items))]

    def pick_or_blank(self, items):
        """GAS の pick_ は空の一覧だと undefined（シートでは空欄）になる。"""
        return self.pick(items) if items else ""

    def shuffle(self, items):
        a = list(items)
        for i in range(len(a) - 1, 0, -1):
            j = int(self.rng.random() * (i + 1))
            a[i], a[j] = a[j], a[i]
        return a

    def generate(self, req: Request, standby_index: int = 0, title_start: int = 0, max_count: int | None = None,
                 ignore_cooldown: bool = False) -> Result:
        bank = self.bank
        cat = next((c for c in CATEGORY_NAMES if c in req.category), None)
        warnings = []
        paired = bank.paired.get(cat)
        letter = ""
        used = {} if ignore_cooldown else last_used(self.usage_rows, req.company, req.category)
        recent = {t for t, d in used.items() if (self.now - d).total_seconds() / 86400 < COOLDOWN_DAYS}
        if paired:
            if not req.title_choice:
                raise ValueError(f"カテゴリ「{req.category}」は「職種名選択(6重め/7軽めのみ・必須)」列で職種名を選択してください")
            sel = req.title_choice.split("｜", 1)[-1]
            entry = next((e for e in paired if e["title"] == sel), None)
            if not entry:
                raise ValueError(f"「{sel}」が{req.commute}用の土台の{CATEGORY_NUMBER_LABEL.get(cat, cat)}シートに見つかりません。"
                                 f"入稿予定表の職種名選択を、{req.commute}の候補から選び直してください"
                                 "（通勤と入寮では職種名の一覧が違います）")
            titles, contents, letter = [entry["title"]], entry["contents"], entry["letter"]
            if not contents:
                raise ValueError(f"「{entry['title']}」のお仕事内容(D列以降)が見つかりません")
            if entry["title"] in recent:
                raise ValueError(f"重複警告: {entry['title']}は {req.company} で{used[entry['title']]:%m/%d}に使っています"
                                 f"（{COOLDOWN_DAYS}日たつまで同じ職種名は使えません）。入稿予定表の職種名選択で別の職種名を選んでください")
        else:
            all_titles = bank.job_titles.get(req.category) or []
            if not all_titles:
                raise ValueError(f"カテゴリ「{req.category}」の職種名が見つかりません")
            contents = bank.job_contents.get(cat) or []
            if not contents:
                raise ValueError(f"カテゴリ「{cat}」の仕事内容が見つかりません")
            titles = [t for t in all_titles if t not in recent]
            if not titles:
                raise ValueError(f"重複警告: カテゴリ「{req.category}」({req.company})は全職種名が使用履歴に存在しています。")

        company = bank.companies.get(req.company)
        if not company:
            raise ValueError(f"会社「{req.company}」が会社情報マスターに見つかりません(登録済み: {', '.join(bank.companies)})")
        ng = bank.ng_by_company.get(req.company)
        if ng is None:
            key = next((k for k in bank.ng_by_company if k in req.company), None)
            ng = bank.ng_by_company[key] if key else []
        locations = [l for l in bank.locations
                     if not any(n == l[0] or n == l[0] + l[1] or n in l[0] + l[1] for n in ng)]
        if not locations:
            raise ValueError("使用できる勤務地がありません(NGエリアで全件除外された可能性があります)")
        target = len(locations) if req.count is None else req.count
        if max_count is not None and target > max_count:
            warnings.append(f"⚠️カテゴリ「{req.category}」({req.company})は上限に近づいたため、{target}件→{max_count}件に減らしました")
            target = max_count
        if target > len(locations):
            warnings.append(f"⚠️カテゴリ「{req.category}」({req.company})は原稿数{target}件に対して使える勤務地が"
                            f"{len(locations)}件のため、{target - len(locations)}件は勤務地が重複します")

        image_cat = req.image_category or bank.image_category_by_job.get(cat)
        images = bank.images_by_category.get(image_cat) or []
        if bank.dorm:
            return self.generate_dorm(req, cat, titles, contents, letter, company, locations, target, images,
                                      standby_index, title_start, warnings)

        man = re.fullmatch(r"(\d+)\s*万", req.salary_pattern or "")
        offsets, salary_pool = None, []
        from_rule = self.rule_salaries(req.salary_rule, target) if req.salary_rule else None
        if from_rule:
            pass
        elif man:
            base = int(man.group(1))
            offsets = self.shuffle(range(10000))[:min(target or 10000, 10000)]
        else:
            salary_pool = bank.salary_patterns.get(req.salary_pattern) or []

        pool = bank.standby_keywords.get(cat) or STANDBY_KEYWORDS_BY_CATEGORY.get(cat) or STANDBY_KEYWORDS_FALLBACK
        standby = req.standby_keyword or (pool[standby_index] if standby_index < len(pool) else self.pick(pool))

        rows, counts, cache = [], {}, {}
        remaining, title_idx, offset_idx, guard = target, title_start, 0, 0
        seg_used = set()
        guard_max = max(1000, -(-target // max(len(locations), 1)) + 10)
        while remaining > 0 and guard < guard_max:
            title = titles[title_idx % len(titles)]
            for _ in range(len(locations)):
                if remaining <= 0:
                    break
                loc = self.next_location(req.company, locations, seg_used)
                content = contents[int(self.rng.random() * len(contents))]
                image = self.pick(images) if images else ""
                if from_rule:
                    salary = from_rule()
                elif offsets is not None:
                    lower = base * 10000 + offsets[offset_idx % len(offsets)]
                    offset_idx += 1
                    upper = js_round(lower * 1.25)
                    detail = (_fill(self.pick(bank.salary_detail_templates), [str(lower), str(upper)])
                              if bank.salary_detail_templates else f"月給{lower:,}円〜{upper:,}円")
                    salary = {"lower": str(lower), "upper": str(upper), "detail": detail}
                else:
                    salary = self.pick(salary_pool) if salary_pool else None
                standby_title = self.pick(titles)
                rows.append(self.build_row(req, title, content, cat, company, loc, image, salary, standby,
                                           standby_title, letter, cache))
                counts[title] = counts.get(title, 0) + 1
                remaining -= 1
            title_idx += 1
            guard += 1
        if remaining > 0:
            warnings.append(f"⚠️カテゴリ「{req.category}」({req.company})は目標{target}件のうち{len(rows)}件しか生成できませんでした")
        return Result(rows, counts, warnings)

    def next_location(self, company: str, locations: list, seg_used: set):
        st = self.location_queues.setdefault(company or "_", [])
        if len(seg_used) >= len(locations):
            seg_used.clear()
        skipped, loc, guard = [], None, 0
        while loc is None and guard < len(locations) * 3 + 10:
            guard += 1
            if not st:
                st.extend(self.shuffle(locations))
            cand = st.pop()
            if cand in seg_used:
                skipped.append(cand)
                continue
            loc = cand
        if loc is None:
            loc = locations[int(self.rng.random() * len(locations))]
        if skipped:
            st[:0] = skipped
        seg_used.add(loc)
        return loc

    # ---- 1件分 ----
    def build_row(self, req: Request, title, content, cat, company, loc, image, salary, standby, standby_title,
                  letter, cache) -> dict:
        bank = self.bank
        row = {h: bank.fixed_template.get(h, "") for h in QMATE_HEADERS}
        set_empty = lambda k, v: row.__setitem__(k, v) if row.get(k, "") == "" else None
        row["更新種別|必須"] = req.update_type or "登録"
        row["ステータス|必須"] = req.status or "公開"
        if image:
            row["求人ページ用画像1"] = image
        row["応募時メール送信先1|必須"] = company.get("応募時メール送信先1", "")
        row["採用担当者名"] = "採用担当"
        row["掲載企業名|必須"] = "非公開"
        row["勤務地：都道府県|必須"], row["勤務地：市区町村|必須"] = loc
        row["雇用形態|必須"] = req.employment
        shift = "二交代・夜勤あり" if is_night(req.night) else "二交代・夜勤なし"
        row["職種名|必須"] = f"＜{standby_title or title}＞{shift}・{standby}" if standby else f"＜{standby_title or title}＞{shift}"
        if title_measure_kind(req.title_measure) == 2:
            m2 = bank.measure2
            end = req.box_word or bank.dedup_word or ""
            if m2["fixed1"] or m2["benefit"] or m2["fixed2"]:
                row["求人ボックス用職種名"] = self.measure2_title(m2, title, shift, end)
            else:
                b = f"「{title}」{shift}／{'／'.join(TITLE_MEASURE_2_PHRASES)}"
                with_d = f"{b}／{end}" if end else ""
                row["求人ボックス用職種名"] = with_d if with_d and js_len(with_d) <= TITLE_LIMIT else b
        elif bank.personas and bank.appeals:
            row["求人ボックス用職種名"] = self.measure1_title(cache, title, shift, req.box_word or bank.dedup_word or "")
        else:
            row["求人ボックス用職種名"] = title
        set_empty("職種カテゴリー(大分類)|必須", QMATE_CATEGORY[0])
        set_empty("職種カテゴリー(中分類)|必須", QMATE_CATEGORY[1])
        set_empty("職種カテゴリー(小分類)|必須", QMATE_CATEGORY[2])
        row["仕事内容|必須"] = f"{content}\n\n{company.get('仕事内容の後に入れる項目', '')}"
        qk = find_parts_key(bank, "応募資格")
        if qk:
            row["応募資格・条件|必須"] = self.pick(bank.parts[qk])
        set_empty("性別制限|必須", "なし")
        if salary and salary.get("hourly"):
            row["給与形態|必須"] = "時給"
        elif salary and salary.get("monthly"):
            row["給与形態|必須"] = "月給"
        set_empty("給与形態|必須", "月給")
        set_empty("給与金額表示形式", "範囲表記")
        if salary:
            row["給与_下限"], row["給与_上限"] = salary["lower"], salary["upper"]
            row["基本給|▲必須"], row["詳細な給与情報"] = salary["lower"], salary["detail"]
        else:
            set_empty("給与_下限", "300000")
            set_empty("給与_上限", "380000")
            set_empty("基本給|▲必須", "300000")
        set_empty("勤務形態", "シフト制")
        wk = find_work_time_key(bank, req.night)
        if wk:
            row["勤務時間|必須"] = self.pick(bank.parts[wk])
        set_empty("給与形態に応じた労働時間（日給・週給・月給・年俸のみ）|▲必須", "160")
        if bank.parts.get("休日休暇"):
            row["休日休暇"] = self.pick(bank.parts["休日休暇"])
        set_empty("固定残業の有無|必須", "なし")
        set_empty("社会保険", "健康保険,厚生年金,雇用保険,労災保険")
        bk = find_parts_key(bank, "待遇")
        if bk:
            row["待遇・福利厚生"] = self.pick(bank.parts[bk])
        set_empty("受動喫煙対策|必須", "屋外喫煙所あり")
        set_empty("試用期間の有無|必須", "なし")
        set_empty("給与同条件選択", "本採用時と同じ")
        set_empty("勤務時間同条件選択", "本採用時と同じ")
        if bank.parts.get("キャッチコピー"):
            row["キャッチコピー"] = self.pick(bank.parts["キャッチコピー"])
        flow = self.pick(bank.parts["選考フロー"]) if bank.parts.get("選考フロー") else ""
        row["選考フロー"] = f"{flow}\n\n【会社所在地】\n{company.get('会社所在地_住所', '')}"
        set_empty("応募受付完了メール要否", "送信する")
        row["応募受付完了メール：件名"] = company.get("応募受付完了メール件名", "")
        row["応募受付完了メール：本文"] = company.get("応募受付完了メール本文", "")
        row["メモ"] = self.memo(req, cat, salary, image, loc, company, letter)
        for k in ("給与_下限", "給与_上限", "基本給|▲必須"):
            try:
                row[k] = str(js_round(float(row[k]))) if row[k] != "" else ""
            except ValueError:
                pass
        return row

    # ---- 給与設定シートの金額帯 ----
    def rule_salaries(self, rule: dict, target: int):
        """給与設定シートの1行から、原稿1件ずつの給与を返す関数を作る。

        幅があれば、下限は 給与_下限〜給与_下限＋幅−1 から重ならないように選ぶ（GAS の「○○万」と同じ作り方）。
        上限は 給与_上限 が空欄なら下限×1.25、入っていれば 給与_上限 に下限と同じばらつきを足す。
        """
        width = rule.get("width") or 0
        offsets = self.shuffle(range(width))[:min(target or width, width)] if width else [0]
        hourly = rule.get("form") == "時給"
        state = {"i": 0}

        def nxt() -> dict:
            off = offsets[state["i"] % len(offsets)]
            state["i"] += 1
            lower = rule["lower"] + off
            upper = rule["upper"] + off if rule.get("upper") else js_round(lower * 1.25)
            if hourly:
                ml, mu = lower * HOURS_PER_DAY * DAYS_PER_MONTH, upper * HOURS_PER_DAY * DAYS_PER_MONTH
                detail = (f"〈時給〉{lower}円〜{upper}円\n{self.pick(MONTHLY_EXAMPLE_LABELS)}{ml:,}円〜{mu:,}円"
                          f"(1日{HOURS_PER_DAY}時間×月{DAYS_PER_MONTH}日勤務の場合)")
            else:
                detail = (_fill(self.pick(self.bank.salary_detail_templates), [str(lower), str(upper)])
                          if self.bank.salary_detail_templates else f"月給{lower:,}円〜{upper:,}円")
            return {"lower": str(lower), "upper": str(upper), "detail": detail,
                    "hourly": hourly, "monthly": not hourly}
        return nxt

    # ---- 入寮用（入寮用 GAS の generateBatch_・buildRow_） ----
    def generate_dorm(self, req, cat, titles, contents, letter, company, locations, target, images,
                      standby_index, title_start, warnings) -> Result:
        bank = self.bank
        salary_pool = bank.salary_patterns.get(req.salary_pattern) or []
        from_rule = self.rule_salaries(req.salary_rule, target) if req.salary_rule else None
        pool = (bank.standby_titles or bank.standby_keywords.get(cat) or STANDBY_KEYWORDS_BY_CATEGORY.get(cat)
                or STANDBY_KEYWORDS_FALLBACK)
        standby = req.standby_keyword or (pool[standby_index] if standby_index < len(pool) else self.pick(pool))
        # 予約1行の原稿は職種名を1つに固定する（S列・T列で同じ職種名を使う）
        title = titles[title_start % len(titles)] if title_start else titles[int(self.rng.random() * len(titles))]
        rows, cache = [], {}
        remaining, guard = target, 0
        guard_max = max(1000, -(-target // max(len(locations), 1)) + 10)
        while remaining > 0 and guard < guard_max:
            for loc in self.shuffle(locations):
                if remaining <= 0:
                    break
                content = contents[int(self.rng.random() * len(contents))]
                image = self.pick(images) if images else ""
                if from_rule:
                    salary = from_rule()
                elif bank.hourly:
                    h = self.pick(bank.hourly)
                    line = h["template"] or f"〈時給〉{h['lower']}円〜{h['upper']}円"
                    label = self.pick(MONTHLY_EXAMPLE_LABELS)
                    ml, mu = h["lower"] * HOURS_PER_DAY * DAYS_PER_MONTH, h["upper"] * HOURS_PER_DAY * DAYS_PER_MONTH
                    salary = {"lower": str(h["lower"]), "upper": str(h["upper"]), "hourly": True,
                              "detail": f"{line}\n{label}{ml:,}円〜{mu:,}円"
                                        f"(1日{HOURS_PER_DAY}時間×月{DAYS_PER_MONTH}日勤務の場合)"}
                else:
                    salary = self.pick(salary_pool) if salary_pool else None
                standby_title = self.pick(titles)
                rows.append(self.build_row_dorm(req, title, content, cat, company, loc, image, salary, standby,
                                                standby_title, letter, cache))
                remaining -= 1
            guard += 1
        if remaining > 0:
            warnings.append(f"⚠️カテゴリ「{req.category}」({req.company})は目標{target}件のうち{len(rows)}件しか生成できず"
                            "打ち切りました(勤務地数が少ないなどの可能性があります)")
        return Result(rows, {title: len(rows)} if rows else {}, warnings)

    def build_row_dorm(self, req: Request, title, content, cat, company, loc, image, salary, standby, standby_title,
                       letter, cache) -> dict:
        bank = self.bank
        row = {h: bank.fixed_template.get(h, "") for h in QMATE_HEADERS}
        set_empty = lambda k, v: row.__setitem__(k, v) if row.get(k, "") == "" else None
        row["更新種別|必須"] = req.update_type or "登録"
        row["ステータス|必須"] = req.status or "公開"
        if image:
            row["求人ページ用画像1"] = image
        row["応募時メール送信先1|必須"] = company.get("応募時メール送信先1", "")
        row["採用担当者名"] = "採用担当"
        row["掲載企業名|必須"] = "非公開"
        row["勤務地：都道府県|必須"], row["勤務地：市区町村|必須"] = loc
        row["雇用形態|必須"] = req.employment
        shift = "二交代・夜勤あり" if is_night(req.night) else "二交代・夜勤なし"
        row["職種名|必須"] = f"＜{standby_title or title}＞{shift}・{standby}" if standby else (standby_title or title)
        if bank.nyuryo_titles:
            cands = [r for r in bank.nyuryo_titles if r["night"] == shift or not r["night"]] or bank.nyuryo_titles
            k1 = list(dict.fromkeys(r["keyword1"] for r in cands if r["keyword1"]))
            k2 = list(dict.fromkeys(r["keyword2"] for r in cands if r["keyword2"]))
            dedup = req.box_word or cands[0]["dedup"]
            row["求人ボックス用職種名"] = self.nyuryo_title(cache, k1, k2, title, shift, dedup) if k1 and k2 else title
        elif bank.personas and bank.appeals:
            row["求人ボックス用職種名"] = self.measure1_title(cache, title, shift, req.box_word or bank.dedup_word or "")
        else:
            row["求人ボックス用職種名"] = title
        set_empty("職種カテゴリー(大分類)|必須", QMATE_CATEGORY[0])
        set_empty("職種カテゴリー(中分類)|必須", QMATE_CATEGORY[1])
        set_empty("職種カテゴリー(小分類)|必須", QMATE_CATEGORY[2])
        tail = company.get("仕事内容の後に入れる項目", "")
        tk = find_parts_key(bank, "お仕事内容の上")
        top = self.pick(bank.parts[tk]) if tk and bank.parts[tk] else ""
        row["仕事内容|必須"] = f"{top}\n\n{content}\n\n{tail}" if top else f"{content}\n\n{tail}"
        qk = find_parts_key(bank, "応募資格")
        if qk:
            row["応募資格・条件|必須"] = self.pick_or_blank(bank.parts[qk])
        set_empty("性別制限|必須", "なし")
        if salary and salary.get("hourly"):
            row["給与形態|必須"] = "時給"
        elif salary and salary.get("monthly"):
            row["給与形態|必須"] = "月給"
        else:
            set_empty("給与形態|必須", "月給")
        set_empty("給与金額表示形式", "範囲表記")
        if salary:
            row["給与_下限"], row["給与_上限"] = salary["lower"], salary["upper"]
            row["基本給|▲必須"], row["詳細な給与情報"] = salary["lower"], salary["detail"]
        else:
            set_empty("給与_下限", "300000")
            set_empty("給与_上限", "380000")
            set_empty("基本給|▲必須", "300000")
        set_empty("勤務形態", "シフト制")
        wk = find_work_time_key_dorm(bank, req.night)
        if wk:
            row["勤務時間|必須"] = self.pick_or_blank(bank.parts[wk])
        set_empty("給与形態に応じた労働時間（日給・週給・月給・年俸のみ）|▲必須", "160")
        if "休日休暇" in bank.parts:
            row["休日休暇"] = self.pick_or_blank(bank.parts["休日休暇"])
        set_empty("固定残業の有無|必須", "なし")
        set_empty("社会保険", "健康保険,厚生年金,雇用保険,労災保険")
        bk = find_parts_key(bank, "待遇")
        if bk:
            row["待遇・福利厚生"] = self.pick_or_blank(bank.parts[bk])
        set_empty("受動喫煙対策|必須", "屋外喫煙所あり")
        set_empty("試用期間の有無|必須", "なし")
        set_empty("給与同条件選択", "本採用時と同じ")
        set_empty("勤務時間同条件選択", "本採用時と同じ")
        if "キャッチコピー" in bank.parts:
            row["キャッチコピー"] = self.pick_or_blank(bank.parts["キャッチコピー"])
        flow = self.pick_or_blank(bank.parts["選考フロー"]) if "選考フロー" in bank.parts else ""
        row["選考フロー"] = f"{flow}\n\n【会社所在地】\n{company.get('会社所在地_住所', '')}"
        set_empty("応募受付完了メール要否", "送信する")
        row["応募受付完了メール：件名"] = company.get("応募受付完了メール件名", "")
        row["応募受付完了メール：本文"] = company.get("応募受付完了メール本文", "")
        row["メモ"] = self.memo(req, cat, salary, image, loc, company, letter)
        for k in ("給与_下限", "給与_上限", "基本給|▲必須"):
            try:
                row[k] = str(js_round(float(row[k]))) if row[k] != "" else ""
            except ValueError:
                pass
        return row

    def nyuryo_title(self, cache: dict, k1: list, k2: list, title: str, shift: str, dedup: str) -> str:
        """入寮タイトルのキーワード①×②の組み合わせから、50文字以内のものを選ぶ（入寮用 GAS の buildNyuryoTitle50Cached_）。"""
        key = (title, shift, dedup)
        if key not in cache:
            with_d, without_d = [], []
            for a in k1:
                for b in k2:
                    base = f"{a}{title}／{shift}／{b}"
                    if js_len(base) <= TITLE_LIMIT:
                        without_d.append(base)
                    if dedup and js_len(f"{base}／{dedup}") <= TITLE_LIMIT:
                        with_d.append(f"{base}／{dedup}")
            fallback = None
            if not with_d and not without_d:
                fallback = f"{min(k1, key=js_len)}{title}／{shift}／{min(k2, key=js_len)}"
            cache[key] = (with_d, without_d, fallback)
        with_d, without_d, fallback = cache[key]
        return self.pick(with_d) if with_d else self.pick(without_d) if without_d else fallback

    def memo(self, req: Request, cat, salary, image, loc, company, letter) -> str:
        created = req.created or self.now.date()
        code = re.match(r"\d*", CATEGORY_NUMBER_LABEL.get(cat, "")).group(0) + letter
        return "-".join(str(x) for x in [
            22, created.strftime("%y%m%d"), COMMUTE_CODE.get(req.commute, ""), EMPLOYMENT_CODE.get(req.employment, 3),
            code, salary["lower"] if salary else "", salary["upper"] if salary else "", image or "",
            loc[0] + loc[1], company.get("求人メモ用会社名") or company.get("会社名", "")])

    # ---- 求人ボックス用職種名（T列） ----
    def measure1_title(self, cache: dict, title: str, shift: str, dedup: str) -> str:
        if title not in cache:
            with_d, without_d = [], []
            for p in self.bank.personas:
                for a in self.bank.appeals:
                    base = f"{p}{title}／{shift}／{a}"
                    if js_len(base) <= TITLE_LIMIT:
                        without_d.append(base)
                    if dedup and js_len(f"{base}／{dedup}") <= TITLE_LIMIT:
                        with_d.append(f"{base}／{dedup}")
            fallback = None
            if not with_d and not without_d:
                sp = min(self.bank.personas, key=len)
                sa = min(self.bank.appeals, key=len)
                fallback = f"{sp}{title}／{shift}／{sa}"
            cache[title] = (with_d, without_d, fallback)
        with_d, without_d, fallback = cache[title]
        return self.pick(with_d) if with_d else self.pick(without_d) if without_d else fallback

    def measure2_title(self, pools: dict, title: str, shift: str, end: str) -> str:
        head = f"「{title}」{shift}"
        join = lambda parts: "／".join(p for p in parts if p)
        length = lambda g, k, benefits: js_len(join([head, g, *benefits, k, end]))
        pick_from = lambda lst, shortest: (min(lst, key=len) if shortest else self.pick(lst)) if lst else ""
        g_short, k_short = pick_from(pools["fixed1"], True), pick_from(pools["fixed2"], True)
        g, k = pick_from(pools["fixed1"], False), pick_from(pools["fixed2"], False)
        benefits = []
        if pools["benefit"]:
            min_benefit = min(len(b) for b in pools["benefit"])
            room = lambda gg, kk: TITLE_LIMIT - length(gg, kk, []) - 1
            fits = lambda gg, kk: room(gg, kk) >= min_benefit
            chosen = None
            for _ in range(30):
                gg, kk = pick_from(pools["fixed1"], False), pick_from(pools["fixed2"], False)
                if fits(gg, kk):
                    chosen = (gg, kk)
                    break
            if not chosen:
                for cand in ((g_short, k_short), (g_short, ""), ("", "")):
                    if fits(*cand):
                        chosen = cand
                        break
            first = None
            if chosen:
                g, k = chosen
                r = room(g, k)
                for _ in range(40):
                    c = self.pick(pools["benefit"])
                    if len(c) <= r:
                        first = c
                        break
                if first is None:
                    ok = [c for c in pools["benefit"] if len(c) <= r]
                    first = self.pick(ok) if ok else None
            if first is None:
                first, g, k = min(pools["benefit"], key=len), "", ""
            benefits.append(first)
            used, misses, tries = set(), 0, 0
            max_tries = min(len(pools["benefit"]), 60) * 2
            while len(benefits) < TITLE_MAX_BENEFIT_WORDS and tries < max_tries and misses < 12:
                tries += 1
                i = int(self.rng.random() * len(pools["benefit"]))
                if i in used:
                    continue
                used.add(i)
                c = pools["benefit"][i]
                if c in benefits:
                    continue
                if length(g, k, benefits + [c]) <= TITLE_LIMIT:
                    benefits.append(c)
                    misses = 0
                else:
                    misses += 1
        elif length(g, k, []) > TITLE_LIMIT:
            g, k = g_short, k_short
        return join([head, g, *benefits, k, end])


# ---------------------------------------------------------------- スプレッドシートから動かす
def run(settings: dict, target: dict, req: Request, *, record_usage: bool = True, ignore_cooldown: bool = False,
        rng: random.Random | None = None, log=print, dorm: bool | None = None) -> Result:
    """土台と本体を読んで、予約1行分の原稿を作る（dorm なら入寮用の作り方。省略時は req.commute で決める）。
    record_usage なら土台の使用履歴を更新する。"""
    from .sheet import Spreadsheet

    base = Spreadsheet(dict(settings, spreadsheet_id=target["base_spreadsheet_id"]))
    main = Spreadsheet(dict(settings, spreadsheet_id=target["spreadsheet_id"]))
    cat = next((c for c in CATEGORY_NAMES if c in req.category), None)
    log("土台を読み込んでいます")
    bank = load_bank(base.sources() + main.sources(), {cat} if cat else set(), dorm=req.commute == "入寮" if dorm is None else dorm)
    usage = base.usage_rows(USAGE_SHEET)
    gen = Generator(bank, usage, rng=rng)
    result = gen.generate(req, ignore_cooldown=ignore_cooldown)
    for name, n in bank.error_cells.items():
        result.warnings.append(f"⚠️土台の「{name}」シートに、読めていないセル（#REF! など）が{n}個あります。"
                               "その文例は使っていません。IMPORTRANGE の参照先を確かめてください")
    if record_usage:
        base.write_usage(USAGE_SHEET, update_usage(usage, req.company, req.category, result.title_counts, gen.now))
    return result
