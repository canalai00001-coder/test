"""入稿原稿（テンプレート(固定列) と同じ列構成）のルールチェック。

GAS の検品シートが見ている項目（空欄・給与の数値・メモとの一致・文字数・重複）に加えて、
マニュアルや記録用シートに書かれている運用ルール（給与下限、絵文字、削除済みキーワード、
年間休日の表記）を見る。severity が error のものが1件でもあればそのシートは入稿しない。
"""
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass

LABOR_HOURS_COL = "給与形態に応じた労働時間（日給・週給・月給・年俸のみ）"
NEEDS_LABOR_HOURS = ("日給", "週給", "月給", "年俸")


@dataclass
class Issue:
    severity: str  # error / warning / info
    column: str
    message: str
    source: str = "rule"  # rule / ai
    suggestion: str = ""

    def to_dict(self):
        return asdict(self)


def base_name(header: str) -> str:
    """'職種名|必須' → '職種名'"""
    return header.split("|")[0].strip()


def nfkc(s) -> str:
    return unicodedata.normalize("NFKC", s or "").strip()


def to_int(s) -> int | None:
    t = nfkc(s).replace(",", "").replace("円", "")
    return int(t) if re.fullmatch(r"\d+", t) else None


# 絵文字の判定。★☆◎■◆●○▼▲※ など飾りに使う記号は対象外。
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF✀-➿⬅-⬇⭐⭕️‍"
    "☀-☄☇-⛿]"
)


def find_emoji(text: str) -> list[str]:
    return sorted(set(_EMOJI.findall(text or "")) - {"️", "‍"})


@dataclass
class Memo:
    """求人メモ: 22-261020-1-1-12-302919-378649-200-埼玉県熊谷市-ArK株式会社/H"""
    job_no: str
    salary_min: int | None
    salary_max: int | None
    image_no: str
    location: str
    company: str


def parse_memo(memo: str) -> Memo | None:
    parts = (memo or "").split("-")
    if len(parts) < 10:
        return None
    job = re.match(r"\d+", parts[4])
    company = "-".join(parts[9:]).split("/")[0].strip()
    return Memo(job.group(0) if job else "", to_int(parts[5]), to_int(parts[6]),
                parts[7].strip(), parts[8].strip(), company)


def night_shift(row: dict) -> str | None:
    """勤務時間の書き方から夜勤の有無を読む。読めなければ None。"""
    t = nfkc(row.get("勤務時間", ""))
    if "夜勤なし" in t:
        return "夜勤なし"
    if "夜勤あり" in t or "夜間" in t or "夜勤" in t:
        return "夜勤あり"
    return None


class Manuscript:
    """出力シート1枚分。"""

    def __init__(self, name: str, table: list[list[str]]):
        self.name = name
        self.headers = table[0] if table else []
        self.raw_rows = [r for r in table[1:] if any(c.strip() for c in r)]
        names = [base_name(h) for h in self.headers]
        self.rows = [dict(zip(names, r + [""] * (len(names) - len(r)))) for r in self.raw_rows]

    def data_hash(self) -> str:
        s = json.dumps([self.headers] + self.raw_rows, ensure_ascii=False)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def check_row(row: dict, headers: list[str], rules: dict) -> list[Issue]:
    issues: list[Issue] = []
    add = lambda sev, col, msg: issues.append(Issue(sev, col, msg))

    # 必須項目
    for h in headers:
        if h.endswith("|必須") and not row.get(base_name(h), "").strip():
            add("error", base_name(h), "必須項目が空欄です")
    wage_type = nfkc(row.get("給与形態"))
    if wage_type in NEEDS_LABOR_HOURS:
        for col in ("基本給", LABOR_HOURS_COL):
            if col in row and not row[col].strip():
                add("error", col, f"給与形態が{wage_type}のときは必須です")

    # 制限の事由
    for flag, reason in (("年齢制限の有無", "年齢制限事由"), ("性別制限", "性別制限事由")):
        if nfkc(row.get(flag)) == "あり" and not row.get(reason, "").strip():
            add("error", reason, f"{flag}が「あり」なのに事由が空欄です")

    # 給与
    fmt = nfkc(row.get("給与金額表示形式"))
    lo, hi = to_int(row.get("給与_下限")), to_int(row.get("給与_上限"))
    if fmt == "範囲表記":
        if lo is None:
            add("error", "給与_下限", f"数値ではありません（{row.get('給与_下限', '')}）")
        if hi is None:
            add("error", "給与_上限", f"数値ではありません（{row.get('給与_上限', '')}）")
        if lo is not None and hi is not None and lo > hi:
            add("error", "給与_下限", f"下限 {lo:,} が上限 {hi:,} より大きくなっています")
    elif fmt == "固定表記" and to_int(row.get("給与_固定")) is None:
        add("error", "給与_固定", f"数値ではありません（{row.get('給与_固定', '')}）")

    # メモとの一致
    memo = parse_memo(row.get("メモ", ""))
    job = None
    if row.get("メモ") and memo is None:
        add("error", "メモ", "求人メモの形式が読めません")
    if memo:
        job = rules["job_numbers"].get(memo.job_no)
        if memo.salary_min is not None and lo is not None and memo.salary_min != lo:
            add("error", "給与_下限", f"メモの給与下限 {memo.salary_min:,} と一致しません（{lo:,}）")
        if memo.salary_max is not None and hi is not None and memo.salary_max != hi:
            add("error", "給与_上限", f"メモの給与上限 {memo.salary_max:,} と一致しません（{hi:,}）")
        img = row.get("求人ページ用画像1", "").strip()
        if memo.image_no and img and memo.image_no != img:
            add("error", "求人ページ用画像1", f"メモの画像番号 {memo.image_no} と一致しません（{img}）")
        place = nfkc(row.get("勤務地：都道府県")) + nfkc(row.get("勤務地：市区町村"))
        if memo.location and place and nfkc(memo.location) != place:
            add("error", "勤務地：市区町村", f"メモの勤務地「{memo.location}」と一致しません（{place}）")
        email = rules.get("company_emails", {}).get(memo.company)
        if email and nfkc(row.get("応募時メール送信先1")) != email:
            add("error", "応募時メール送信先1", f"{memo.company} の送信先は {email} です")

    # 給与下限（マニュアル 2026.10.1～）
    night = night_shift(row)
    if job and wage_type == "月給" and lo is not None:
        floor = rules.get("salary_floor", {}).get(job, {})
        if night and night in floor and lo < floor[night]:
            add("error", "給与_下限", f"{job}・{night}の給与下限 {floor[night]:,} 円を下回っています（{lo:,}）")
        elif floor and not night:
            add("info", "勤務時間", "夜勤の有無が読み取れないため給与下限を判定していません")

    # 夜勤の表記ゆれ
    title = nfkc(row.get("求人ボックス用職種名"))
    if night == "夜勤なし" and "夜勤あり" in title or night == "夜勤あり" and "夜勤なし" in title:
        add("error", "求人ボックス用職種名", f"勤務時間は{night}ですが、職種名の表記と食い違っています")
    keywords = [k.strip() for k in nfkc(row.get("キーワードリスト（複数選択可）")).split(",") if k.strip()]
    if night == "夜勤なし":
        bad = [k for k in keywords if k in rules.get("night_keywords_in_list", [])]
        if bad:
            add("warning", "キーワードリスト（複数選択可）", f"夜勤なしの原稿に夜勤系キーワードがあります: {'、'.join(bad)}")

    # 求人ボックス用職種名
    limit = rules.get("boxjob_title_max_len", 50)
    if len(row.get("求人ボックス用職種名", "")) > limit:
        add("error", "求人ボックス用職種名", f"{limit}文字を超えています（{len(row['求人ボックス用職種名'])}文字）")

    # 削除済みキーワード
    banned = [k for k in keywords if k in rules.get("banned_keywords", [])]
    if banned:
        add("warning", "キーワードリスト（複数選択可）", f"見直しで削除したキーワードが入っています: {'、'.join(banned)}")

    # 絵文字
    for col in rules.get("no_emoji_columns", []):
        if col == "仕事内容" and job in rules.get("emoji_allowed_jobs_for_description", []):
            continue
        found = find_emoji(row.get(col, ""))
        if found:
            add("warning", col, f"絵文字が残っています（{''.join(found)}）。飾り紐に置き換えてください")

    # 古い表記
    for p in rules.get("outdated_phrases", []):
        if re.search(p["pattern"], row.get(p["column"], "")):
            add("warning", p["column"], p["message"])
    return issues


def check_sheet(ms: Manuscript, rules: dict) -> list[list[Issue]]:
    """行ごとの指摘のリストを返す（ms.rows と同じ順番）。"""
    results = [check_row(r, ms.headers, rules) for r in ms.rows]

    def dupes(key):
        seen = {}
        for i, r in enumerate(ms.rows):
            k = key(r)
            if k:
                seen.setdefault(k, []).append(i)
        return {k: v for k, v in seen.items() if len(v) > 1}

    for title, idx in dupes(lambda r: r.get("求人ボックス用職種名", "").strip()).items():
        for i in idx:
            results[i].append(Issue("warning", "求人ボックス用職種名",
                                    f"同じ職種名がシート内に{len(idx)}件あります"))
    for place, idx in dupes(lambda r: nfkc(r.get("勤務地：都道府県")) + nfkc(r.get("勤務地：市区町村"))).items():
        for i in idx:
            results[i].append(Issue("warning", "勤務地：市区町村", f"勤務地「{place}」がシート内で重複しています"))
    return results


def status_of(issues: list[Issue]) -> str:
    if any(i.severity == "error" for i in issues):
        return "NG"
    if any(i.severity == "warning" for i in issues):
        return "要確認"
    return "OK"
