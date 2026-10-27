"""ルールで判定できるチェック。

AI に聞く前に、必須漏れ・数値の形式・選択肢・年齢の逆転・最低賃金割れなど、
機械的に白黒がつくものはここで止める。severity が error のものが1件でもあれば投稿しない。
"""
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass

PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]


@dataclass
class Issue:
    severity: str  # error / warning / info
    field: str
    message: str
    source: str = "rule"  # rule / ai
    suggestion: str = ""

    def to_dict(self):
        return asdict(self)


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").strip()


def parse_int(text: str) -> int | None:
    """"1,600円" "25.6万円" "256000" などを整数に。読めなければ None。"""
    t = nfkc(text).replace(",", "").replace("¥", "").replace("円", "")
    if not t:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)万", t)
    if m:
        return int(round(float(m.group(1)) * 10000))
    if re.fullmatch(r"\d+", t):
        return int(t)
    return None


def build_job(row, fields: list[dict]) -> dict:
    """シートの1行を {項目key: 値(文字列)} にする。"""
    return {f["key"]: row.get(f["column"]) for f in fields}


def job_hash(job: dict) -> str:
    """承認後にシートが書き換えられていないかを確かめるためのハッシュ。"""
    s = json.dumps(job, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def check_fields(job: dict, fields: list[dict]) -> list[Issue]:
    issues = []
    for f in fields:
        key, label = f["key"], f["label"]
        v = job.get(key, "")
        if not v:
            if f.get("required"):
                issues.append(Issue("error", key, f"{label}が空欄です"))
            continue
        t = f.get("type", "text")
        if t == "int":
            n = parse_int(v)
            if n is None:
                issues.append(Issue("error", key, f"{label}「{v}」を数値として読めません"))
                continue
            if "min" in f and n < f["min"]:
                issues.append(Issue("error", key, f"{label}が{f['min']}未満です（{n}）"))
            if "max" in f and n > f["max"]:
                issues.append(Issue("error", key, f"{label}が{f['max']}を超えています（{n}）"))
        elif t == "enum":
            if nfkc(v) not in [nfkc(c) for c in f["choices"]]:
                issues.append(Issue("error", key,
                                    f"{label}「{v}」は選択肢にありません（{' / '.join(f['choices'])}）"))
        elif t == "prefecture":
            if nfkc(v) not in PREFECTURES:
                issues.append(Issue("error", key, f"{label}「{v}」は都道府県名として正しくありません"))
        if "max_len" in f and len(v) > f["max_len"]:
            issues.append(Issue("error", key, f"{label}が{f['max_len']}文字を超えています（{len(v)}文字）"))
        if "min_len" in f and len(v) < f["min_len"]:
            issues.append(Issue("warning", key, f"{label}が短すぎます（{len(v)}文字）"))
    return issues


def check_consistency(job: dict, rules: dict) -> list[Issue]:
    issues = []
    get_int = lambda k: parse_int(job.get(k, ""))

    age_min, age_max = get_int("age_min"), get_int("age_max")
    if age_min is not None and age_max is not None and age_min > age_max:
        issues.append(Issue("error", "age_min", f"年齢下限（{age_min}）が上限（{age_max}）より大きくなっています"))

    pref = nfkc(job.get("prefecture", ""))
    address = nfkc(job.get("address", ""))
    if pref and address and pref in PREFECTURES:
        other = next((p for p in PREFECTURES if address.startswith(p)), None)
        if other and other != pref:
            issues.append(Issue("error", "address", f"都道府県（{pref}）と住所（{other}…）が食い違っています"))

    wage_type, wage, monthly = nfkc(job.get("wage_type", "")), get_int("wage"), get_int("monthly_income")
    if wage_type == "時給" and wage:
        floor = rules.get("min_wage_by_prefecture", {}).get(pref, rules.get("min_wage_default"))
        if floor and wage < floor:
            issues.append(Issue("error", "wage", f"時給{wage}円が最低賃金の設定値（{floor}円）を下回っています"))
        if monthly:
            lo, hi = rules.get("hourly_monthly_hours_range", [100, 230])
            hours = monthly / wage
            if not lo <= hours <= hi:
                issues.append(Issue("warning", "monthly_income",
                                    f"月収例{monthly:,}円は時給{wage:,}円の約{hours:.0f}時間分です。"
                                    f"金額か時給の入力ミスの可能性があります"))
    elif wage_type == "日給" and wage and monthly:
        lo, hi = rules.get("daily_monthly_days_range", [15, 26])
        days = monthly / wage
        if not lo <= days <= hi:
            issues.append(Issue("warning", "monthly_income",
                                f"月収例{monthly:,}円は日給{wage:,}円の約{days:.1f}日分です"))
    elif wage_type == "月給" and wage and monthly and monthly < wage:
        issues.append(Issue("warning", "monthly_income", "月収例が月給より少なくなっています"))

    gender = nfkc(job.get("gender", ""))
    if gender and gender not in ("不問", "男女不問"):
        issues.append(Issue("warning", "gender",
                            f"性別「{gender}」の指定があります。男女雇用機会均等法により、"
                            "性別を限定した募集は原則できません。求人票に載せない運用か確認してください"))
    if age_max is not None or (age_min is not None and age_min > 18):
        issues.append(Issue("info", "age_max",
                            "年齢制限があります。労働施策総合推進法の例外事由に当たるか確認してください"))
    return issues


def check_duplicates(jobs: list[dict]) -> dict[str, list[Issue]]:
    seen: dict[str, int] = {}
    for j in jobs:
        no = j.get("job_no", "")
        if no:
            seen[no] = seen.get(no, 0) + 1
    return {no: [Issue("error", "job_no", f"求人No「{no}」がシート内で{n}回出てきます")]
            for no, n in seen.items() if n > 1}


def run_rules(job: dict, fields: list[dict], rules: dict) -> list[Issue]:
    return check_fields(job, fields) + check_consistency(job, rules)
