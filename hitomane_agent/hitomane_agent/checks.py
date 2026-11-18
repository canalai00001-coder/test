"""入稿前のチェック（出力シート。新フォーマットと、施策で作る旧フォーマット）。

見出し・空欄・「あり・なし」・日付・給与・お仕事番号（メモ）との一致・重複を見る。
CSV は Shift_JIS（cp932）で書くので、その文字コードで書けない文字（絵文字など）もここで見つける。
severity が error のものが1件でもあれば、そのシートは入稿しない。
"""
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date

from .headers import NEW_FORMAT, OLD_FORMAT, OLD_FORMAT_HEAD, OLD_FORMAT_WIDTH


@dataclass
class Issue:
    severity: str  # error / warning
    column: str
    message: str

    def to_dict(self):
        return asdict(self)


def nfkc(s) -> str:
    return unicodedata.normalize("NFKC", s or "").strip()


def to_int(s) -> int | None:
    t = nfkc(s).replace(",", "").replace("円", "")
    return int(t) if re.fullmatch(r"\d+", t) else None


def to_date(s) -> date | None:
    m = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", (s or "").strip())
    if not m:
        return None
    try:
        return date(*map(int, m.groups()))
    except ValueError:
        return None


# スプレッドシートのエラー値（IMPORTRANGE が読めないときの #REF! など）
SHEET_ERROR = re.compile(r"#(?:REF!|N/A|VALUE!|NAME\?|DIV/0!|NUM!|ERROR!|NULL!|SPILL!|CALC!)"
                         r"|Cannot find range or sheet|imported range|^Loading\.\.\.$", re.M)


def not_cp932(text: str) -> list[str]:
    """Shift_JIS（cp932）で書けない文字。"""
    bad = []
    for ch in text or "":
        try:
            ch.encode("cp932")
        except UnicodeEncodeError:
            if ch not in bad:
                bad.append(ch)
    return bad


@dataclass
class Memo:
    """お仕事番号: 3-261117-1-1-6E-351200-439000-製造(268)-大阪府泉南市-canal benefits株"""
    salary_min: int | None
    salary_max: int | None
    image: str
    location: str


def parse_memo(memo: str) -> Memo | None:
    parts = (memo or "").split("-")
    if len(parts) < 10:
        return None
    return Memo(to_int(parts[5]), to_int(parts[6]), parts[7].strip(), parts[8].strip())


class Manuscript:
    """出力シート1枚分（1行目が見出し）。"""

    def __init__(self, name: str, table: list[list[str]], segments: list[int] | None = None):
        self.name = name
        # 予約行ごとの区切り（行の番号。0 始まり）。ツールで作った原稿だけが持つ。勤務地の重複を予約行ごとに数えるのに使う
        self.segments = segments
        self.headers = [str(h).strip() for h in table[0]] if table else []
        width = len(self.headers)
        self.raw_rows = [(list(r) + [""] * width)[:width] for r in table[1:] if any(str(c).strip() for c in r)]
        # 同じ見出しが2つあるとき（旧フォーマットの「応募方法」）は1つ目の値
        self.rows = [{h: v for h, v in reversed(list(zip(self.headers, r)))} for r in self.raw_rows]

    @property
    def is_old_format(self) -> bool:
        return self.headers == OLD_FORMAT

    def data_hash(self) -> str:
        s = json.dumps([self.headers] + self.raw_rows, ensure_ascii=False)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def check_header(ms: Manuscript) -> list[Issue]:
    if ms.headers in (NEW_FORMAT, OLD_FORMAT):
        return []
    if len(ms.headers) == OLD_FORMAT_WIDTH and ms.headers[:len(OLD_FORMAT_HEAD)] == OLD_FORMAT_HEAD:
        diff = next((f"{i + 1}列目が「{a}」（旧フォーマットは「{b}」）" for i, (a, b) in enumerate(zip(ms.headers, OLD_FORMAT))
                     if a != b), "")
        return [Issue("error", "見出し", f"見出しが旧フォーマットと違います：{diff}")]
    diff = next((f"{i + 1}列目が「{a}」（新フォーマットは「{b}」）" for i, (a, b) in enumerate(zip(ms.headers, NEW_FORMAT))
                 if a != b), f"列の数が {len(ms.headers)}（新フォーマットは {len(NEW_FORMAT)}）")
    return [Issue("error", "見出し", f"見出しが新フォーマットと違います：{diff}")]


def check_row(row: dict, rules: dict) -> list[Issue]:
    """1行分。旧フォーマットの行（「都道府県」の列がある）は rules の old_format の列で見る。"""
    old = "都道府県" in row and "勤務地_都道府県" not in row
    cols = rules.get("old_format", {}) if old else rules
    issues: list[Issue] = []
    add = lambda sev, col, msg: issues.append(Issue(sev, col, msg))

    for col, v in row.items():
        if SHEET_ERROR.search(v or ""):
            add("error", col, f"スプレッドシートのエラー値が入っています（{v.strip()[:30]}）")
        bad = not_cp932(v)
        if bad:
            add("error", col, f"CSV（Shift_JIS）に書けない文字があります：{' '.join(bad)}")

    for col in cols.get("required_columns", []):
        if not (row.get(col) or "").strip():
            add("error", col, "空欄です（必須）")
    for col in cols.get("usual_columns", []):
        if not (row.get(col) or "").strip():
            add("warning", col, "空欄です（いつもは入っている列です）")
    for col in cols.get("flag_columns", []):
        v = (row.get(col) or "").strip()
        if v not in ("", "TRUE", "FALSE"):
            add("error", col, f"「TRUE」か空欄にしてください（今は「{v}」）")
    for col in cols.get("yes_no_columns", []):
        v = (row.get(col) or "").strip()
        if v not in ("あり", "なし"):
            add("error", col, f"「あり」か「なし」を入れてください（今は{f'「{v}」' if v else '空欄'}）")

    start, end = (row.get("開始日") or "").strip(), (row.get("終了日") or "").strip()
    ds, de = to_date(start), to_date(end)
    for col, raw, d in (("開始日", start, ds), ("終了日", end, de)):
        if raw and d is None:
            add("error", col, f"日付は 2026/11/17 の形にしてください（今は「{raw}」）")
    if ds and de and ds > de:
        add("error", "開始日", f"開始日 {start} が終了日 {end} より後です")

    status = (row.get("ステータス") or "").strip()
    if status and status not in rules["status_values"]:
        add("error", "ステータス", f"「{'」か「'.join(rules['status_values'])}」を入れてください（今は「{status}」）")

    lo_raw, hi_raw = row.get("基本給_最低額", ""), row.get("基本給_最高額", "")
    lo, hi = to_int(lo_raw), to_int(hi_raw)
    if lo_raw.strip() and lo is None:
        add("error", "基本給_最低額", f"数字ではありません（「{lo_raw}」）")
    if hi_raw.strip() and hi is None:
        add("error", "基本給_最高額", f"数字ではありません（「{hi_raw}」）")
    if lo is not None and hi is not None and lo > hi:
        add("error", "基本給_最低額", f"最低額 {lo} が最高額 {hi} より大きいです")

    memo = parse_memo(row.get("お仕事番号", ""))
    if memo:
        place = _place(row)
        pairs = (("基本給_最低額", memo.salary_min, lo), ("基本給_最高額", memo.salary_max, hi))
        for col, want, got in pairs:
            if want is not None and got is not None and want != got:
                add("error", "お仕事番号", f"お仕事番号の{col.split('_')[1]} {want} と {col} {got} が違います")
        image = (row.get("画像名1") or "").strip()
        if memo.image and image and nfkc(memo.image) != nfkc(image):
            add("error", "お仕事番号", f"お仕事番号の画像名「{memo.image}」と画像名1「{image}」が違います")
        if memo.location and place and nfkc(memo.location) != place:
            add("error", "お仕事番号", f"お仕事番号の勤務地「{memo.location}」と勤務地「{place}」が違います")
    elif (row.get("お仕事番号") or "").strip():
        add("warning", "お仕事番号", "お仕事番号がいつもの形（3-日付-…-会社名）ではないため、給与・画像・勤務地と照らし合わせていません")
    return issues


def _place(row: dict) -> str:
    if "都道府県" in row and "勤務地_都道府県" not in row:
        return nfkc(row.get("都道府県")) + nfkc(row.get("市区町村"))
    return nfkc(row.get("勤務地_都道府県")) + nfkc(row.get("勤務地_市区町村"))


def check_sheet(ms: Manuscript, rules: dict) -> tuple[list[Issue], list[list[Issue]]]:
    """(シート全体の指摘, 行ごとの指摘のリスト（ms.rows と同じ順番）)。"""
    sheet = check_header(ms)
    if sheet:
        return sheet, [[] for _ in ms.rows]
    if not ms.rows:
        return [Issue("error", "全体", "原稿がありません")], []
    results = [check_row(r, rules) for r in ms.rows]

    def dupes(key):
        seen = {}
        for i, r in enumerate(ms.rows):
            k = key(r)
            if k:
                seen.setdefault(k, []).append(i)
        return {k: v for k, v in seen.items() if len(v) > 1}

    for code, idx in dupes(lambda r: (r.get("募集番号") or "").strip()).items():
        for i in idx:
            results[i].append(Issue("error", "募集番号", f"募集番号「{code}」がシート内に{len(idx)}件あります（後の行で上書きされます）"))
    place_of = _place
    if ms.segments:
        # GAS の⑤検品と同じく、予約行ごと（区切りごと）に勤務地の重複を数える
        bounds = sorted(set(ms.segments) | {0}) + [len(ms.rows)]
        for no, (a, b) in enumerate(zip(bounds, bounds[1:]), start=1):
            seen = {}
            for i in range(a, b):
                if place_of(ms.rows[i]):
                    seen.setdefault(place_of(ms.rows[i]), []).append(i)
            for place, idx in seen.items():
                if len(idx) > 1:
                    for i in idx:
                        results[i].append(Issue("warning", "市区町村" if ms.is_old_format else "勤務地_市区町村",
                                                f"勤務地「{place}」が同じ予約行（{no}つ目）の中で重複しています"))
    else:
        for place, idx in dupes(place_of).items():
            for i in idx:
                results[i].append(Issue("warning", "市区町村" if ms.is_old_format else "勤務地_市区町村",
                                        f"勤務地「{place}」がシート内で重複しています"))
    codes = sorted({(r.get("拠点コード") or "").strip() for r in ms.rows} - {""})
    if len(codes) > 1:
        sheet.append(Issue("warning", "拠点コード", f"1枚のシートに拠点コードが{len(codes)}つあります（{'・'.join(codes)}）"))
    return sheet, results


def status_of(issues: list[Issue]) -> str:
    if any(i.severity == "error" for i in issues):
        return "NG"
    if any(i.severity == "warning" for i in issues):
        return "要確認"
    return "OK"
