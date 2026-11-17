"""原稿の生成（ヒトマネ用 GAS の「③予約リストを一括実行」の新FMTを Python に移したもの）。

元は hitomane_agent/gas/コード.js（【AI用】ヒトマネ 求人原稿自動生成 に付いている GAS。2026-11-17 に clasp で取り出した）。
関数ごとに GAS の名前を書いておく（hmBuildContentBank_ → build_bank など）。Q-mate 版の生成（qmate_agent/generator.py）とは別物。

- 土台（＜土台＞ヒトマネ 求人原稿自動生成）のシートを、GAS と同じくタブ名と中身（見出し）から役割を判定して読む。
- 予約リストは【AI用】の「ヒトマネ実行設定」シート（4行目から。1行＝1回の生成予約）。グループ番号（1-1, 1-2 …）が
  同じ行は、GAS と同じく1つの原稿にまとめる。
- 職種名・仕事内容の使用履歴は読むだけ（確かめている間は書かない。GAS から切り替えるときに書く）。
- 作るのは新FMT（192列）だけ。旧FMT の予約は、ヒトマネに取り込めないので作らない。

GAS の癖もそのまま移している（同じ原稿を作るため）。気づいたもの：
  - 仕事内容のシート（1クルマ など）は、1行目の見出し「仕事内容」も候補に入る（hmBuildContentBank_ が全部のセルを読むため）
  - 給与のシートは4行目から読む（3行目にある給与は使われない）
  - タイトルのシートは500行目までしか読まない
"""
import math
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .headers import NEW_FORMAT

BASE_SPREADSHEET_ID = "1fTDLsTOIcf-JONthvU-60rWqUVSF6mkvK2HmYcSb3CI"  # HM_BASE_SPREADSHEET_ID
CONFIG_SHEET_NAME = "ヒトマネ実行設定"
LIST_SHEET_NAME = "_ヒトマネ_プルダウン用リスト（自動生成・編集不要）"
USAGE_SHEET_NAME = "ヒトマネ_アカウント×職種名_使用履歴"
CONTENT_USAGE_SHEET_NAME = "ヒトマネ_アカウント×職種_仕事内容使用履歴"
INSPECTION_SHEET_NAME = "ヒトマネ_検品シート"
COOLDOWN_DAYS = 30
CONFIG_DATA_START_ROW = 4
MEDIA_CODE = 3

CATEGORY_NUMBER_LABEL = {
    "クルマ": "1クルマ", "工場": "2工場", "軽作業": "3軽作業", "電子部品": "4電子部品", "半導体": "5半導体",
    "重め": "6重め", "軽め": "7軽め", "梱包": "8梱包", "検査": "9検査", "ピッキング": "10ピッキング",
    "仕分け": "11仕分け", "シール貼り": "12シール貼り",
}
CATEGORY_NAMES = list(CATEGORY_NUMBER_LABEL)
COMMUTE_CODE = {"通勤": 1, "入寮": 2}
EMPLOYMENT_CODE = {"正社員": 1, "契約社員": 2, "その他": 3}
WORKTIME_COLUMN_LETTERS = ["CW", "CB", "CC", "CE", "CH", "CI", "CJ", "CL", "CO", "CP", "CQ", "CS", "CV"]
IMAGE_LIKE_LABELS = ["軽作業", "製造", "工場", "入寮", "寮画像", "クルマ", "梱包", "検査", "電子部品", "半導体", "ピッキング",
                     "仕分け", "シール貼り"]

# 旧FMT の見出し（109列。シートの役割の判定に使う。HITOMANE_HEADERS）
OLD_HEADERS = ["募集番号", "ステータス", "開始日", "終了日", "拠点コード", "拠点", "お仕事番号", "都道府県", "市区町村", "媒体", "費用", "メモ", "応募フォーム", "閲覧数（PC)", "閲覧数（MOBILE)", "閲覧数（SMARTPHONE)", "給与方法", "シフト", "応募方法", "定員", "募集職種", "一覧用給与", "給与", "一覧用PR", "PR", "早朝", "朝", "昼", "夕方", "夜", "深夜", "駅チカ・駅ナカ", "オープニングスタッフ", "高校生歓迎", "大学生歓迎", "主婦・主夫歓迎", "シフト制勤務", "短時間勤務（4時間以内）", "時間曜日応相談", "即日勤務OK", "未経験者歓迎", "交通費支給", "交通費一部支給", "社内割引あり", "日祝給料アップ", "社員登用あり", "寮・社宅あり", "まかないあり", "食事補助", "制服貸与", "髪型自由", "服装自由", "土日のみOK", "平日のみOK", "週払いOK", "日払いOK", "土日祝勤務歓迎", "車通勤応相談", "フリーター歓迎", "語学力を活かせる", "研修制度あり", "経験者歓迎", "前払い応相談", "早朝・深夜勤務", "土日祝・面接可", "大量募集", "Wワーク歓迎", "仕事ブランクOK", "画像名一覧用", "画像名1", "画像名2", "画像名3", "画像名4", "画像名5", "画像1キャプション", "画像2キャプション", "画像3キャプション", "画像4キャプション", "画像5キャプション", "仕事内容", "最低給与額", "勤務時間", "勤務期間", "勤務地", "交通アクセス", "年齢制限", "応募資格", "待遇", "地図用テキスト", "地図用タイトル", "地図用住所", "その他地図用テキスト", "その他地図用タイトル", "その他地図用住所", "応募方法", "担当", "オンライン面接予約機能", "応募時面接予約任意", "面接締切時応募続行", "優先度", "掲載用拠点名", "受付電話番号", "カスタム検索キーワード", "媒体出稿時の名称", "ファイル名", "コンテントタイプ", "雇用形態", "案件詳細URL", "Indeed広告用参照番号"]

# 新FMT の固定列（HITOMANE_NEW_FIXED_VALUES。GAS のまま）
NEW_FIXED_VALUES = {"案件タイプ": "有料人材紹介案件", "掲載用拠点名": "非公開", "職種カテゴリ": "製造・生産業務（その他）", "雇用形態": "正社員", "早朝": "あり", "朝": "あり", "昼": "あり", "夕方": "あり", "夜": "あり", "深夜": "あり", "基本給_給与タイプ": "月給", "基本給_定額": "なし", "平均所定労働時間": "160", "平均勤務日数": "20", "一律支給される諸手当_定額": "なし", "固定残業代の有無": "なし", "固定残業代の支払額_定額": "なし", "固定残業代の支払額_最低額": "", "固定残業代の支払額_最高額": "", "固定残業時間": "", "固定残業時間を超えた場合の追加支払い": "なし", "試用期間の有無": "あり", "試用期間_期間": "2", "試用期間_単位": "週間", "試用期間_労働条件の差異": "なし", "試用期間_労働条件の差異_給与": "なし", "試用期間_労働条件の差異_労働時間": "なし", "試用期間_労働条件の差異_その他（雇用形態や手当など）": "なし", "試用期間_給与条件_給与タイプ": "", "試用期間_給与条件_定額": "なし", "試用期間_給与条件_最低額": "", "試用期間_給与条件_最高額": "", "試用期間_給与条件_タスク_単位": "", "試用期間_給与条件_タスク_時間": "", "試用期間_一律支給される諸手当_定額": "なし", "試用期間_一律支給される諸手当_最低額": "", "試用期間_一律支給される諸手当_最高額": "", "試用期間_給与条件_固定残業代の有無": "なし", "試用期間_給与条件_固定残業代の支払額_定額": "なし", "試用期間_給与条件_固定残業代の支払額_最低額": "", "試用期間_給与条件_固定残業代の支払額_最高額": "", "試用期間_給与条件_固定残業時間": "", "試用期間_給与条件_固定残業時間を超えた場合の追加支払い": "なし", "地図用テキスト": "勤務地", "地図用タイトル": "勤務地はこちら", "実働時間_固定_1": "なし", "休憩時間_変動_1": "なし", "実働時間_固定_2": "なし", "休憩時間_変動_2": "なし", "実働時間_固定_3": "なし", "休憩時間_変動_3": "なし", "勤務形態_固定時間制": "なし", "勤務形態_シフト制": "あり", "勤務形態_変形労働制": "なし", "勤務形態_フレックスタイム制度": "なし", "勤務形態_専門業務型裁量労働制": "なし", "勤務形態_企画業務型裁量労働制": "なし", "勤務形態_事業場外みなし労働時間制": "なし", "勤務形態_高度プロフェッショナル制": "なし", "Indeed連携用_シフト": "週4日以上OK", "社会保険_厚生年金": "あり", "社会保険_健康保険": "あり", "社会保険_雇用保険": "あり", "社会保険_労災保険": "あり", "選択できない社会保険がある場合の理由": "", "受動喫煙対策_屋内禁煙": "なし", "受動喫煙対策_屋外喫煙可": "なし", "受動喫煙対策_屋内原則禁煙（ただし、適用除外の場所あり）": "あり", "受動喫煙対策_屋内喫煙可": "なし", "受動喫煙対策_屋内喫煙可（ただし、特定の喫煙可能室または喫煙目的室のみ）": "なし", "受動喫煙対策_内定時までに開示": "なし", "担当": "採用担当", "オンライン面接予約機能": "なし", "応募時面接予約任意": "なし", "面接締切時応募続行": "なし", "応募フォーム": "応募項目パターン１", "駅チカ・駅ナカ": "なし", "オープニングスタッフ": "なし", "高校生歓迎": "なし", "大学生歓迎": "なし", "主婦・主夫歓迎": "なし", "シフト制勤務": "なし", "短時間勤務（4時間以内）": "なし", "時間曜日応相談": "なし", "即日勤務OK": "あり", "未経験者歓迎": "あり", "交通費支給": "あり", "交通費一部支給": "なし", "社内割引あり": "なし", "日祝給料アップ": "なし", "社員登用あり": "なし", "寮・社宅あり": "あり", "まかないあり": "なし", "食事補助": "あり", "制服貸与": "あり", "髪型自由": "なし", "服装自由": "なし", "土日のみOK": "なし", "平日のみOK": "なし", "週払いOK": "あり", "日払いOK": "なし", "土日祝勤務歓迎": "なし", "車通勤応相談": "なし", "フリーター歓迎": "あり", "語学力を活かせる": "なし", "研修制度あり": "あり", "経験者歓迎": "あり", "前払い応相談": "なし", "早朝・深夜勤務": "なし", "土日祝・面接可": "なし", "大量募集": "なし", "Wワーク歓迎": "なし", "仕事ブランクOK": "なし", "カスタム検索キーワード": "", "媒体": "自社"}

BASE_ROLE_PREFIXES = ["職種名", "仕事内容(", "職種内容ペア(", "パーツ(PR等・正社員)", "会社情報マスター", "勤務地・NGエリア",
                      "給与パターン", "画像カテゴリー一覧", "勤務時間パターン(新FMT用", "組み立てタイトル(募集職種用)"]


class GenerateError(Exception):
    """GAS が予約行を赤くして止めるときのエラー（文言も GAS と同じ）。"""


# ---------------------------------------------------------------- シート（GAS の Sheet の代わり）

class Grid:
    """シート1枚分の値（書式付きの文字列）。GAS の getLastRow / getLastColumn / getRange().getValues() の代わり。"""

    def __init__(self, name: str, values: list[list]):
        self.name = name
        rows = [[("" if c is None else str(c)) for c in r] for r in values]
        while rows and not any(c != "" for c in rows[-1]):
            rows.pop()
        self.last_row = len(rows)
        self.last_col = max((max((i + 1 for i, c in enumerate(r) if c != ""), default=0) for r in rows), default=0)
        self.rows = rows

    def get(self, row: int, col: int, nrows: int, ncols: int) -> list[list[str]]:
        """1始まりの行・列から nrows × ncols（足りないところは空）。"""
        out = []
        for r in range(row - 1, row - 1 + max(nrows, 0)):
            src = self.rows[r] if 0 <= r < len(self.rows) else []
            out.append([(src[c] if c < len(src) else "") for c in range(col - 1, col - 1 + ncols)])
        return out

    def row(self, row: int, col: int, ncols: int) -> list[str]:
        return self.get(row, col, 1, ncols)[0]


def _header_row_guess(sh: Grid) -> int:  # hmGetHeaderRowGuess_
    best, best_count = 1, -1
    for r in range(1, min(6, sh.last_row) + 1):
        count = sum(1 for v in sh.row(r, 1, min(sh.last_col, 30)) if v != "")
        if count > best_count:
            best, best_count = r, count
    return best


def _top_block_text(sh: Grid) -> str:  # hmGetTopBlockText_
    max_row, max_col = min(6, sh.last_row), min(sh.last_col, 40)
    if max_row < 1 or max_col < 1:
        return ""
    return " ".join(" ".join(r) for r in sh.get(1, 1, max_row, max_col))


def _worktime_header_row(sh: Grid) -> int:  # hmFindWorkTimeHeaderRow_
    for r in range(1, min(sh.last_row, 10) + 1):
        vals = [v.strip() for v in sh.row(r, 1, min(sh.last_col, 25))]
        if sum(1 for v in vals if v in WORKTIME_COLUMN_LETTERS) >= 5:
            return r
    return -1


def _image_header_row(sh: Grid) -> int:  # hmFindImageHeaderRow_
    for r in range(1, min(sh.last_row, 20) + 1):
        vals = [v.strip() for v in sh.row(r, 1, min(sh.last_col, 20))]
        if sum(1 for v in vals if v in IMAGE_LIKE_LABELS) >= 2:
            return r
    return -1


def _signature_row(sh: Grid, required: list[str]) -> int:  # hmFindSignatureRow_
    for r in range(1, min(6, sh.last_row) + 1):
        joined = " ".join(sh.row(r, 1, min(sh.last_col, 40)))
        if all(s in joined for s in required):
            return r
    return _header_row_guess(sh)


def _header_row_index(sh: Grid, headers: list[str], min_match: int) -> int:  # hmFindHeaderRowIndex_
    for r in range(1, min(6, sh.last_row) + 1):
        if sum(1 for v in sh.row(r, 1, min(sh.last_col, 260)) if v in headers) >= min_match:
            return r
    return -1


def classify(sh: Grid) -> str:  # hmClassifySheet_
    name = sh.name
    if name == CONFIG_SHEET_NAME:
        return "ヒトマネ実行設定シート"
    if name == LIST_SHEET_NAME:
        return "プルダウン用リスト(自動生成・無視してOK)"
    if name == USAGE_SHEET_NAME:
        return "使用履歴シート(自動生成)"
    if name == CONTENT_USAGE_SHEET_NAME:
        return "仕事内容使用履歴シート(自動生成)"
    if name == INSPECTION_SHEET_NAME:
        return "検品シート(自動生成)"
    if name.startswith("ヒトマネ出力_"):
        return "生成済み出力シート(過去分)"
    if "新FMT" in name:
        return "新FMT(テンプレ・未対応)"
    if name == "職種名管理":
        return "職種名管理(6重め/7軽め使用状況)"
    if name == "タイトル":
        return "組み立てタイトル(募集職種用)"
    if sh.last_col >= 100 and _header_row_index(sh, OLD_HEADERS, 40) >= 0:
        return "旧FMT(テンプレ)"
    text = _top_block_text(sh)
    if "低額" in text and "基本" in text and "高額" in text:
        return "給与パターン"
    if "画像カテゴリー" in text:
        return "画像カテゴリー一覧"
    if _image_header_row(sh) >= 0:
        return "画像カテゴリー一覧"
    if "都道府県" in text and "市区町村" in text:
        return "勤務地・NGエリア"
    if "会社名" in text and ("応募時メール送信先1" in text or "拠点コード" in text):
        return "会社情報マスター"
    if "PR" in text and "応募資格" in text and "待遇" in text:
        return "パーツ(PR等・正社員)"
    if ("勤務時間_開始_1" in text and "勤務時間_終了_1" in text) or _worktime_header_row(sh) >= 0:
        if "夜勤あり" in name:
            return "勤務時間パターン(新FMT用・夜勤あり)"
        if "夜勤なし" in name:
            return "勤務時間パターン(新FMT用・夜勤なし)"
        return "勤務時間パターン(新FMT用)"
    m = re.match(r"^\d+(重め|軽め)$", name)
    if m:
        return f"職種内容ペア({m.group(1)})"
    m = re.match(r"^\d+(.+)$", name)
    if m and m.group(1) in CATEGORY_NAMES:
        return f"仕事内容({m.group(1)})"
    matched = next((c for c in CATEGORY_NAMES if name == c or c in name), None)
    if matched:
        return f"仕事内容({matched})"
    headers = sh.row(_header_row_guess(sh), 1, min(sh.last_col, 30))
    if sum(1 for h in headers if re.match(r"^\d+\S", h)) >= 3:
        return "職種名"
    return "(未分類 - 手動確認が必要)"


def is_base_role(role: str) -> bool:  # hmIsBaseSheetRole_（読む必要のあるシートだけを読むために使う）
    return any(role.startswith(p) for p in BASE_ROLE_PREFIXES)


# ---------------------------------------------------------------- 土台（コンテンツバンク）

@dataclass
class Bank:
    job_titles: dict = field(default_factory=dict)
    job_contents: dict = field(default_factory=dict)
    parts: dict = field(default_factory=dict)
    companies: dict = field(default_factory=dict)
    locations: list = field(default_factory=list)
    ng_by_company: dict = field(default_factory=dict)
    salary_patterns: dict = field(default_factory=dict)
    images_by_category: dict = field(default_factory=dict)
    image_category_by_job_category: dict = field(default_factory=dict)
    paired_job_data: dict = field(default_factory=dict)
    title_components: dict = field(default_factory=lambda: {"personas": [], "appeals": [], "dedup_word": ""})
    work_time_patterns: list = field(default_factory=list)
    work_time_by_shift: dict = field(default_factory=lambda: {"夜勤あり": [], "夜勤なし": []})
    roles: dict = field(default_factory=dict)  # シート名 → 役割（①シート診断と同じ）


def _js_round(s: str) -> str:
    """GAS の String(Math.round(Number(v)))。数字でなければ "NaN"。"""
    try:
        return str(int(math.floor(float(str(s).strip()) + 0.5)))
    except ValueError:
        return "NaN"


def build_bank(grids: list[Grid]) -> Bank:  # hmBuildContentBank_
    bank = Bank()
    for sh in grids:
        if sh.last_row < 1:
            continue
        role = classify(sh)
        bank.roles[sh.name] = role
        last_col, last_row = sh.last_col, sh.last_row
        if role == "職種名":
            h_row = _header_row_guess(sh)
            headers = sh.row(h_row, 1, last_col)
            data = sh.get(h_row + 1, 1, last_row - h_row, last_col)
            for ci, h in enumerate(headers):
                if re.match(r"^\d+\S", h):
                    bank.job_titles[h] = [r[ci] for r in data if r[ci] != ""]
        elif role == "組み立てタイトル(募集職種用)":
            personas, appeals, dedup = [], [], ""
            for r in sh.get(1, 1, min(last_row, 500), last_col):
                if not re.fullmatch(r"\d+", r[0].strip()):
                    continue
                if r[5] and r[5] not in personas:
                    personas.append(r[5])
                if r[9] and r[9] not in appeals:
                    appeals.append(r[9])
                if r[11]:
                    dedup = r[11]
            bank.title_components = {"personas": personas, "appeals": appeals, "dedup_word": dedup}
        elif role.startswith("職種内容ペア("):
            category = role[7:-1]
            h_row = _signature_row(sh, ["職種名"])
            start = h_row + 1
            bank.paired_job_data.setdefault(category, [])
            if last_row >= start:
                n = last_row - start + 1
                ncols = max(last_col - 4 + 1, 1)
                for r in sh.get(start, 1, n, max(last_col, 4)):
                    title = r[0]
                    if not title:
                        continue
                    contents = [v for v in r[3:3 + ncols] if v != ""]
                    bank.paired_job_data[category].append({"title": title, "letter": r[1].strip(), "contents": contents})
        elif role.startswith("仕事内容("):
            category = role[5:-1]
            pool = bank.job_contents.setdefault(category, [])
            for r in sh.get(1, 1, last_row, last_col):
                pool.extend(v for v in r if v != "")
        elif role == "パーツ(PR等・正社員)":
            h_row = _signature_row(sh, ["PR", "応募資格"])
            headers = sh.row(h_row, 1, last_col)
            start = h_row + 1
            if any(re.search(r"文字まで|文字以内", v) for v in sh.row(start, 1, last_col)):
                start += 1
            data = sh.get(start, 1, last_row - start + 1, last_col)
            for ci, key in enumerate(headers):
                if not key:
                    continue
                pool = bank.parts.setdefault(key, [])
                pool.extend(r[ci] for r in data if r[ci] != "" and not re.search(r"文字まで|文字以内", r[ci]))
        elif role == "会社情報マスター":
            h_row = _signature_row(sh, ["会社名"])
            headers = sh.row(h_row, 1, last_col)
            col = {h: i for i, h in enumerate(headers)}  # 同じ見出しは後ろの列（GAS の colIndex と同じ）
            for r in sh.get(h_row + 1, 1, last_row - h_row, last_col):
                name = r[col["会社名"]] if "会社名" in col else ""
                if not name:
                    continue
                obj, seen = {}, {}
                for i, key in enumerate(headers):
                    if not key:
                        continue
                    seen[key] = seen.get(key, 0) + 1
                    obj[f"{key}#{seen[key]}" if seen[key] >= 2 else key] = r[i]
                bank.companies[name] = obj
        elif role == "勤務地・NGエリア":
            h_row = _signature_row(sh, ["都道府県", "市区町村"])
            headers = sh.row(h_row, 1, last_col)
            col = {h: i for i, h in enumerate(headers)}
            data = sh.get(h_row + 1, 1, last_row - h_row, last_col)
            for r in data:
                pref = r[col["都道府県"]]
                if pref:
                    bank.locations.append({"pref": pref, "city": r[col["市区町村"]]})
            for ci, key in enumerate(headers):
                if not key or key in ("都道府県", "市区町村") or "合体" in key:
                    continue
                ngs = [r[ci] for r in data if r[ci] != ""]
                if ngs:
                    bank.ng_by_company[key] = ngs
        elif role == "給与パターン":
            start = 4
            if last_row >= start:
                n = last_row - start + 1
                for name, sc in (("低額", 1), ("基本", 8), ("高額", 15)):
                    lows = sh.get(start, sc, n, 1)
                    highs = sh.get(start, sc + 3, n, 1)
                    details = sh.get(start, sc + 5, n, 1)
                    pool = []
                    for i in range(n):
                        low = lows[i][0]
                        if low == "":
                            continue
                        high = highs[i][0]
                        pool.append({"lower": _js_round(low), "upper": "" if high == "" else _js_round(high),
                                     "detail": details[i][0]})
                    if pool:
                        bank.salary_patterns[name] = pool
        elif role == "画像カテゴリー一覧":
            h_row = _image_header_row(sh)
            if h_row < 0:
                h_row = _signature_row(sh, ["画像カテゴリー"])
            headers = sh.row(h_row, 1, last_col)
            mapping = sh.row(h_row + 1, 1, last_col)
            is_mapping = "職種" in mapping[0]
            offset = 2 if is_mapping else 1
            data = sh.get(h_row + offset, 1, last_row - h_row - offset + 1, last_col)
            for ci, key in enumerate(headers):
                if not key or key == "画像カテゴリー":
                    continue
                pool = [r[ci] for r in data if r[ci] != ""]
                if pool:
                    bank.images_by_category[key] = pool
                if is_mapping:
                    for jc in [s.strip() for s in re.split(r"[・\s]+", mapping[ci]) if s.strip()]:
                        if jc in CATEGORY_NAMES:
                            bank.image_category_by_job_category[jc] = key
        elif role.startswith("勤務時間パターン(新FMT用"):
            target = (bank.work_time_by_shift["夜勤あり"] if "夜勤あり" in role else
                      bank.work_time_by_shift["夜勤なし"] if "夜勤なし" in role else bank.work_time_patterns)
            letter_row = _worktime_header_row(sh)
            if letter_row >= 0:
                max_col = min(last_col, 25)
                header = [v.strip() for v in sh.row(letter_row, 1, max_col)]
                col_of = {v: i for i, v in enumerate(header) if v in WORKTIME_COLUMN_LETTERS}
                start = letter_row + 1
                if last_row >= start:
                    for r in sh.get(start, 1, last_row - start + 1, max_col):
                        get = lambda letter: (r[col_of[letter]] if letter in col_of else "") or ""
                        if not get("CB") and not get("CC"):
                            continue
                        target.append({"supplement": get("CW"), "start1": get("CB"), "end1": get("CC"),
                                       "min1": get("CE"), "break1": get("CH"), "start2": get("CI"), "end2": get("CJ"),
                                       "min2": get("CL"), "break2": get("CO"), "start3": get("CP"), "end3": get("CQ"),
                                       "min3": get("CS"), "break3": get("CV")})
            else:
                h_row = _signature_row(sh, ["勤務時間_開始_1"])
                start = h_row + 1
                if sum(1 for v in sh.row(start, 1, 13) if re.fullmatch(r"[A-Z]{1,3}", v.strip())) >= 5:
                    start += 1
                if last_row >= start:
                    for r in sh.get(start, 1, last_row - start + 1, 13):
                        if not r[1] and not r[2]:
                            continue
                        keys = ["supplement", "start1", "end1", "min1", "break1", "start2", "end2", "min2", "break2",
                                "start3", "end3", "min3", "break3"]
                        target.append(dict(zip(keys, r)))
    return bank


# ---------------------------------------------------------------- 使用履歴（読むだけ）

@dataclass
class Usage:
    """職種名の使用履歴（会社名, 職種番号, 職種名, 累計使用回数, 累計原稿数, 直近使用日）と、仕事内容の使用履歴。"""
    title_rows: list = field(default_factory=list)
    content_used: dict = field(default_factory=dict)  # "会社名||職種番号" → 使った仕事内容の set


def load_usage(title_values: list[list], content_values: list[list]) -> Usage:  # hmLoadUsageHistoryCache_ ほか
    u = Usage()
    for r in title_values:
        r = [("" if c is None else str(c)) for c in r] + [""] * 6
        u.title_rows.append(r[:6])
    for r in content_values:
        r = [("" if c is None else str(c)) for c in r] + [""] * 3
        u.content_used.setdefault(f"{r[0]}||{r[1]}", set()).add(r[2])
    return u


def _parse_used_at(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).strip().replace(" ", "T"))
    except ValueError:
        return None


def recently_used(company: str, category: str, usage: Usage, now: datetime) -> tuple[set, dict]:  # hmGetRecentlyUsedTitles_
    recent, last = set(), {}
    for comp, cat, title, _, _, last_raw in usage.title_rows:
        if comp != company or cat != category or not last_raw:
            continue
        d = _parse_used_at(last_raw)
        if d is None:  # GAS では Invalid Date（比較はどれも false になり、直近とはみなされない）
            last[title] = None
            continue
        last[title] = d
        if (now - d).total_seconds() / 86400 < COOLDOWN_DAYS:
            recent.add(title)
    return recent, last


def ever_used(company: str, category: str, usage: Usage) -> set:  # hmGetEverUsedTitles_
    return {r[2] for r in usage.title_rows if r[0] == company and r[1] == category and r[2]}


# ---------------------------------------------------------------- 予約リスト

@dataclass
class Target:
    """予約1行（hmRunFromConfig の targets の1つ）。"""
    sheet_row: int
    group_id: str
    seq: int
    creation_date: str
    commute: str
    employment: str
    category: str
    company: str
    format: str
    count: int | None
    count_raw: str
    entry_prefix: str
    status: str
    image_category: str
    salary_pattern: str
    night_shift: str
    paired_title: str
    title_dedup_word: str
    exec_status: str


def read_targets(table: list[list], include_done: bool = False) -> list[Target]:
    """「ヒトマネ実行設定」の表（1行目から）→ 予約行。実行状況の入った行は GAS と同じく飛ばす（include_done で含める）。"""
    out = []
    for i, r in enumerate(table[CONFIG_DATA_START_ROW - 1:]):
        r = [("" if c is None else str(c).strip()) for c in r] + [""] * 16
        group_raw, cdate, commute, employment, category, company, fmt, count_raw, prefix, status, image, salary, night, \
            paired, dedup, exec_status = r[:16]
        sheet_row = CONFIG_DATA_START_ROW + i
        if not category and not company and not count_raw and not group_raw:
            continue
        if exec_status and not include_done:
            continue
        m = re.match(r"^(.+)-(\d+)$", group_raw)
        count = None
        if count_raw != "":
            try:
                count = float(count_raw.replace(",", ""))
                count = int(count) if count == int(count) else count
            except ValueError:
                count = float("nan")
        out.append(Target(sheet_row, m.group(1) if m else f"_単独_{sheet_row}", int(m.group(2)) if m else 0, cdate,
                          commute, employment, category, company, fmt or "旧FMT", count, count_raw, prefix, status,
                          image, salary, night, paired, dedup, exec_status))
    return out


def groups_of(targets: list[Target]) -> dict[str, list[Target]]:
    """グループ番号ごと（出てきた順。中はグループ内の番号順）。"""
    groups: dict[str, list[Target]] = {}
    for t in targets:
        groups.setdefault(t.group_id, []).append(t)
    return {g: sorted(ts, key=lambda t: t.seq) for g, ts in groups.items()}


def parse_creation_date(s: str, today: date) -> date:
    """作成日のセル（2026/11/19 など）。空なら今日（GAS の new Date(creationDate || new Date())）。"""
    s = (s or "").strip()
    if not s:
        return today
    m = re.match(r"^(\d{4})[/\-年](\d{1,2})[/\-月](\d{1,2})", s)
    if not m:
        raise GenerateError(f"作成日「{s}」を日付として読めません")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def add_one_year(d: date) -> date:
    """JavaScript の setFullYear(+1) と同じ（2/29 → 翌年の 3/1）。"""
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return date(d.year + 1, 3, 1)


# ---------------------------------------------------------------- 生成

def _content_category(category: str) -> str | None:
    return next((c for c in CATEGORY_NAMES if c in category), None)


def composed_title(bank: Bank, title: str, night: str, dedup_word: str, rnd: random.Random) -> str:  # hmBuildComposedTitle_
    tc = bank.title_components
    if not tc["personas"] or not tc["appeals"]:
        return title
    persona, appeal = rnd.choice(tc["personas"]), rnd.choice(tc["appeals"])
    shift = "二交代・夜勤あり" if night == "夜勤あり" else "二交代・夜勤なし"
    dedup = dedup_word or tc["dedup_word"] or ""
    return f"「{title}」{persona}／{shift}／{appeal}" + (f"／{dedup}" if dedup else "")


def _find_parts_key(bank: Bank, *subs: str) -> str | None:  # hmFindPartsKey_ / hmFindPartsKeyAll_
    return next((k for k in bank.parts if all(s in k for s in subs)), None)


def part_keys(bank: Bank) -> dict:  # hmResolvePartKeys_（新FMT で使うものだけ）
    return {"qual": _find_parts_key(bank, "応募資格"), "period": _find_parts_key(bank, "勤務期間"),
            "benefit": _find_parts_key(bank, "待遇"), "holiday": _find_parts_key(bank, "休日"),
            "apply": _find_parts_key(bank, "応募方法"), "pr": _find_parts_key(bank, "PR")}


def usable_locations(bank: Bank, company: str) -> list[dict]:
    ng = bank.ng_by_company.get(company)
    if ng is None:
        short = next((k for k in bank.ng_by_company if k in company), None)
        ng = bank.ng_by_company[short] if short else []
    return [loc for loc in bank.locations
            if not any(n == loc["pref"] or n == loc["pref"] + loc["city"] or n in loc["pref"] + loc["city"] for n in ng)]


def target_count(bank: Bank, t: Target) -> int:
    """原稿数（空欄なら NG エリアを除いた勤務地の数）。募集番号の引き継ぎを計算するのに使う。"""
    return len(usable_locations(bank, t.company)) if t.count is None else int(t.count)


@dataclass
class Batch:
    rows: list
    title_counts: dict
    content_counts: dict
    title_end_index: int
    entry_no_end: str


def _entry_numbers(prefix: str):
    m = re.match(r"^(.*?)(\d+)$", prefix or "")
    letters = m.group(1) if m else (prefix or "")
    start = int(m.group(2)) if m else None
    digits = len(m.group(2)) if m else 0

    def number(offset: int) -> str:
        if start is None:
            return letters + str(offset + 1)
        n = start + offset
        return letters + (str(n).zfill(digits) if digits > 1 else str(n))
    return number


def generate_batch(bank: Bank, t: Target, entry_prefix: str, title_start: int, usage: Usage, rnd: random.Random,
                   now: datetime, today: date) -> Batch:  # hmGenerateBatchNewFmt_
    content_category = _content_category(t.category)
    paired = bool(bank.paired_job_data.get(content_category))
    fixed_letter = ""
    if paired:
        if not t.paired_title:
            raise GenerateError(f"カテゴリ「{t.category}」は「職種名選択(6重め/7軽めのみ・必須)」列で職種名を選択してください")
        sel = t.paired_title.split("｜", 1)[1] if "｜" in t.paired_title else t.paired_title
        entry = next((e for e in bank.paired_job_data[content_category] if e["title"] == sel), None)
        if entry is None:
            raise GenerateError(f"「{sel}」が{content_category}シートの職種名一覧に見つかりません")
        titles, contents = [entry["title"]], entry["contents"]
        if not contents:
            raise GenerateError(f"「{entry['title']}」のお仕事内容(D列以降)が見つかりません")
        fixed_letter = entry["letter"]
    else:
        all_titles = bank.job_titles.get(t.category) or []
        if not all_titles:
            raise GenerateError(f"カテゴリ「{t.category}」の職種名が見つかりません")
        contents = bank.job_contents.get(content_category) or []
        if not contents:
            raise GenerateError(f"カテゴリ「{content_category}」の仕事内容が見つかりません")
        recent, last = recently_used(t.company, t.category, usage, now)
        ever = ever_used(t.company, t.category, usage)
        if all(x in ever for x in all_titles):
            raise GenerateError(f"「{t.company}」の「{t.category}」職種名(全{len(all_titles)}件)を全て使い切りました。"
                                "職種名シートに新しい職種名を追加してください。")
        titles = [x for x in all_titles if x not in recent] or list(all_titles)
        # 一度も使っていない職種名が先、そのあとは直近使用日の古い順（Array.sort は安定ソート）
        titles.sort(key=lambda x: (x in ever, last[x].timestamp() if last.get(x) else 0))

    company = bank.companies.get(t.company)
    if company is None:
        raise GenerateError(f"会社「{t.company}」が会社情報マスターに見つかりません")
    locations = usable_locations(bank, t.company)
    if not locations:
        raise GenerateError("使用できる勤務地がありません(NGエリアで全件除外された可能性があります)")
    shuffled = locations[:]
    for i in range(len(shuffled) - 1, 0, -1):  # hmShuffle_（Fisher–Yates）
        j = rnd.randrange(i + 1)
        shuffled[i], shuffled[j] = shuffled[j], shuffled[i]
    count = len(locations) if t.count is None else int(t.count)

    image_key = (t.image_category or bank.image_category_by_job_category.get(content_category)
                 or next((k for k in bank.images_by_category if content_category and content_category in k), None)
                 or next(iter(bank.images_by_category), None))
    images = bank.images_by_category.get(image_key) or []
    salaries = bank.salary_patterns.get(t.salary_pattern) or bank.salary_patterns.get("基本") or []
    keys = part_keys(bank)
    work_pool = (bank.work_time_by_shift.get(t.night_shift) if t.night_shift and bank.work_time_by_shift.get(t.night_shift)
                 else bank.work_time_patterns)
    if not work_pool:
        raise GenerateError("「勤務時間」シート(新FMT用の勤務時間パターン。夜勤あり/なし別、または従来型)が見つかりません")

    used = usage.content_used.get(f"{t.company}||{t.category}", set())
    number = _entry_numbers(entry_prefix)
    creation = parse_creation_date(t.creation_date, today)
    rows, title_counts, content_counts = [], {}, {}
    remaining, title_idx, guard, offset = count, title_start, 0, 0
    guard_max = max(1000, math.ceil(count / max(len(shuffled), 1)) + 10)
    while remaining > 0 and guard < guard_max:
        title = titles[title_idx % len(titles)]
        for loc in shuffled:
            if remaining <= 0:
                break
            unused = [c for c in contents if c not in used]  # hmPickUnusedContent_（使用履歴は読むだけ）
            content = rnd.choice(unused or contents)
            image = rnd.choice(images) if images else ""
            salary = rnd.choice(salaries) if salaries else None
            work = rnd.choice(work_pool)
            rows.append(build_row(bank, title, content, content_category, t, company, loc, image, salary, creation,
                                  number(offset), fixed_letter, work, keys, rnd))
            title_counts[title] = title_counts.get(title, 0) + 1
            content_counts[content] = content_counts.get(content, 0) + 1
            remaining -= 1
            offset += 1
        title_idx += 1
        guard += 1
    return Batch(rows, title_counts, content_counts, title_idx, number(offset))


def build_row(bank: Bank, title: str, content: str, content_category: str, t: Target, company: dict, loc: dict,
              image: str, salary: dict | None, creation: date, entry_number: str, letter: str, work: dict, keys: dict,
              rnd: random.Random) -> dict:  # hmBuildRowNewFmt_
    row = {h: NEW_FIXED_VALUES.get(h, "") for h in NEW_FORMAT}
    row["募集番号"] = entry_number or ""
    row["ステータス"] = t.status or "掲載"
    row["開始日"] = f"{creation:%Y/%m/%d}"
    row["終了日"] = f"{add_one_year(creation):%Y/%m/%d}"
    row["勤務地_都道府県"] = loc["pref"]
    row["勤務地_市区町村"] = loc["city"]
    row["雇用形態"] = t.employment or NEW_FIXED_VALUES["雇用形態"]
    row["募集職種"] = composed_title(bank, title, t.night_shift, t.title_dedup_word, rnd)
    pick = lambda k: rnd.choice(bank.parts[k]) if bank.parts.get(k) else None
    for col, key in (("PR", "pr"), ("勤務期間", "period"), ("応募資格", "qual"), ("待遇", "benefit"), ("休日・休暇", "holiday")):
        if keys[key]:
            row[col] = pick(keys[key])
    row["応募方法"] = company.get("応募方法", "") or ""
    apply_text = pick(keys["apply"]) if keys["apply"] else ""
    row["応募方法_補足"] = "\n".join(x for x in (apply_text, company.get("応募方法#2", "") or "") if x)
    row["仕事内容"] = f"{content}\n\n【受動喫煙対策】受動喫煙対策あり（屋内禁煙）"
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
    if image:
        row["画像名一覧用"] = row["画像名1"] = image
    row["拠点コード"] = company.get("拠点コード", "") or ""
    row["拠点"] = company.get("拠点", "") or ""
    if "電話" in (company.get("応募方法", "") or ""):
        row["受付電話番号"] = company.get("電話応募番号", "") or ""
    cat_label = CATEGORY_NUMBER_LABEL.get(content_category, "")
    cat_code = (re.match(r"^\d+", cat_label).group(0) if re.match(r"^\d+", cat_label) else "") + (letter or "")
    row["お仕事番号"] = "-".join(str(x) for x in (
        MEDIA_CODE, f"{creation:%y%m%d}", COMMUTE_CODE.get(t.commute, ""),
        EMPLOYMENT_CODE.get(t.employment, EMPLOYMENT_CODE["正社員"]), cat_code,
        salary["lower"] if salary else "", salary["upper"] if salary else "", image or "", place,
        company.get("求人メモ用会社名") or company.get("会社名") or ""))
    return row


# ---------------------------------------------------------------- 予約リストの実行（hmRunFromConfig の生成部分）

@dataclass
class GroupResult:
    group_id: str
    name: str            # GAS の出力シート名（ヒトマネ出力_新_G1_会社_カテゴリ_日付）
    company: str
    category: str
    targets: list
    rows: list = field(default_factory=list)
    title_counts: list = field(default_factory=list)  # 予約行ごとの {職種名: 件数}（使用履歴に書くもの）
    content_counts: list = field(default_factory=list)
    error: str = ""
    skipped: list = field(default_factory=list)  # 作らなかった予約行（旧FMT）


def output_name(first: Target, today: date) -> str:
    created = parse_creation_date(first.creation_date, today)
    label = "" if first.group_id.startswith("_単独_") else f"G{first.group_id}_"
    new = "新_" if first.format == "新FMT" else ""
    return f"ヒトマネ出力_{new}{label}{first.company}_{first.category}_{created:%Y%m%d}"[:95]


def run(bank: Bank, usage: Usage, targets: list[Target], only_groups: set | None = None, seed=None,
        now: datetime | None = None, today: date | None = None, stop_on_error: bool = True) -> list[GroupResult]:
    """予約行を GAS と同じ順番（グループの出てきた順・グループ内の番号順）で生成する。

    募集番号の先頭が空の行は、同じ会社の直前の予約行の続きの番号を使う（グループをまたいでも引き継ぐ）。そのため、
    only_groups で一部のグループだけ作るときも、前のグループの番号は数えて引き継ぐ（原稿は作らない）。
    GAS はエラーの行で全体を止めるので、エラーが出たグループのあとのグループは作らない。
    stop_on_error=False なら、エラーのグループだけ飛ばして続ける（入稿予定表の行はそれぞれ別の予定のため）。
    """
    now = now or datetime.now()
    today = today or now.date()
    rnd = random.Random(seed)
    results = []
    continuation: dict[str, str] = {}
    for gid, ts in groups_of(targets).items():
        res = GroupResult(gid, output_name(ts[0], today), ts[0].company, ts[0].category, ts)
        build = only_groups is None or gid in only_groups
        title_index: dict[str, int] = {}
        try:
            for t in ts:
                where = f"行{t.sheet_row}: "
                if not t.category:
                    raise GenerateError(where + "職種番号(カテゴリ)が空です")
                if not t.entry_prefix and not continuation.get(t.company):
                    raise GenerateError(where + "募集番号の先頭が空です(この会社で最初の予約行は必須入力です)")
                if not t.image_category:
                    raise GenerateError(where + "画像カテゴリーが空です(必須入力です)")
                if not t.company:
                    raise GenerateError(where + "会社名が空です")
                if t.count is not None and (t.count != t.count or t.count <= 0):
                    raise GenerateError(where + "原稿数が数値になっていません")
                prefix = t.entry_prefix or continuation[t.company]
                key = f"{t.category}||{t.company}"
                if build and t.format != "新FMT":
                    # 旧FMT はヒトマネに取り込めないので作らない（募集番号の引き継ぎだけ数える）
                    res.skipped.append(f"行{t.sheet_row}（旧FMT）")
                    continuation[t.company] = _entry_numbers(prefix)(target_count(bank, t))
                    continue
                if build:
                    try:
                        b = generate_batch(bank, t, prefix, title_index.get(key, 0), usage, rnd, now, today)
                    except GenerateError as e:
                        raise GenerateError(where + str(e)) from None
                    content_category = _content_category(t.category)
                    if bank.paired_job_data.get(content_category):  # 6重め/7軽めだけ、全期間の使用履歴と照らす
                        dup = [x for x in b.title_counts if x in ever_used(t.company, t.category, usage)]
                        if dup:
                            raise GenerateError(where + f"重複警告: {'、'.join(dup)}は使用履歴に存在しています。")
                    title_index[key] = b.title_end_index
                    continuation[t.company] = b.entry_no_end
                    res.rows.extend(b.rows)
                    res.title_counts.append(b.title_counts)
                    res.content_counts.append(b.content_counts)
                else:
                    continuation[t.company] = _entry_numbers(prefix)(target_count(bank, t))
        except GenerateError as e:
            res.error = str(e)
            res.rows, res.title_counts, res.content_counts = [], [], []
            if build:
                results.append(res)
            if stop_on_error:
                break
            continue
        if build:
            if res.skipped and not res.rows:
                res.error = "旧FMT の予約です。ヒトマネに取り込めるのは新FMT だけのため、ツールでは作りません"
            for t, tc, cc in zip([t for t in ts if t.format == "新FMT"], res.title_counts, res.content_counts):
                remember_usage(usage, t.company, t.category, tc, cc, now)
            results.append(res)
    return results


def remember_usage(usage: Usage, company: str, category: str, title_counts: dict, content_counts: dict,
                   now: datetime) -> None:
    """GAS がグループを作り終えるたびに行う使用履歴の更新（hmUpdateUsageCache_ / hmUpdateContentUsageCache_）を、
    メモリ上だけで行う（シートには書かない）。同じ実行の後ろのグループが、前のグループで使った職種名・仕事内容を避けるため。"""
    stamp = f"{now:%Y-%m-%d %H:%M}"
    for title, n in title_counts.items():
        row = next((r for r in usage.title_rows if r[:3] == [company, category, title]), None)
        if row:
            row[3] = str(int(float(row[3] or 0)) + 1)
            row[4] = str(int(float(row[4] or 0)) + n)
            row[5] = stamp
        else:
            usage.title_rows.append([company, category, title, "1", str(n), stamp])
    usage.content_used.setdefault(f"{company}||{category}", set()).update(content_counts)


# ---------------------------------------------------------------- スプレッドシートから読む（読むだけ）

# 生成に使わない大きいシートは読まない（役割の判定にも影響しない）
SKIP_SHEETS = ("原稿確認用", "テンプレ", "職種名管理", USAGE_SHEET_NAME, CONTENT_USAGE_SHEET_NAME)


def _quote(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def load_base(base_book) -> tuple[list[Grid], Usage]:
    """＜土台＞のシート（書式付きの値）と使用履歴。シートは1回のまとめ読みで読む。"""
    names = [ws.title for ws in base_book.worksheets()]
    want = [n for n in names if not any(s in n for s in SKIP_SHEETS)]
    res = base_book.values_batch_get([_quote(n) for n in want], params={"valueRenderOption": "FORMATTED_VALUE"})
    grids = [Grid(n, vr.get("values", [])) for n, vr in zip(want, res.get("valueRanges", []))]
    ranges = []
    if USAGE_SHEET_NAME in names:
        ranges.append(f"{_quote(USAGE_SHEET_NAME)}!A2:F")
    if CONTENT_USAGE_SHEET_NAME in names:
        ranges.append(f"{_quote(CONTENT_USAGE_SHEET_NAME)}!A2:C")
    got = base_book.values_batch_get(ranges, params={"valueRenderOption": "FORMATTED_VALUE"}).get("valueRanges", []) \
        if ranges else []
    vals = {r.get("range", "").split("!")[0].strip("'"): r.get("values", []) for r in got}
    return grids, load_usage(vals.get(USAGE_SHEET_NAME, []), vals.get(CONTENT_USAGE_SHEET_NAME, []))


def load_config(ai_book) -> list[list]:
    """【AI用】の「ヒトマネ実行設定」シート（1行目から）。"""
    return ai_book.values_get(_quote(CONFIG_SHEET_NAME), params={"valueRenderOption": "FORMATTED_VALUE"}).get("values", [])
