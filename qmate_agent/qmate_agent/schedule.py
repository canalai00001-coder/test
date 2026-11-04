"""入稿予定表の行から、原稿の生成・チェック・入稿までを1回で行う。

入稿予定表の1行 → 実行設定に予約行を追加 → GAS（ウェブアプリ）に生成を頼む
→ 実行設定の実行状況が「✅完了」になるまで待つ → 出力シートをチェック → Q-mate に入稿
"""
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# 実行設定シートの列。通勤用と入寮用で GAS が違い、列の並びも違う（GAS の CONFIG_COLUMNS と同じ並び）。
# 予約行はこの並びで A 列から書き、その右の「実行状況」列を読んで生成の完了を待つ。
CONFIG_FIELDS = {
    "通勤": ["グループ番号", "作成日", "通勤か入寮か", "雇用形態", "職種番号", "会社名", "原稿数", "更新種別",
             "ステータス", "画像カテゴリー", "給与パターン", "夜勤の有無", "スタンバイキーワード", "タイトル(施策)",
             "求人ボックスワード", "職種名選択"],
    "入寮": ["グループ番号", "作成日", "通勤か入寮か", "雇用形態", "職種番号", "会社名", "原稿数", "更新種別",
             "ステータス", "画像カテゴリー", "給与パターン", "夜勤の有無", "スタンバイキーワード",
             "求人ボックスワード", "職種名選択"],
}
COMMUTE_TYPES = tuple(CONFIG_FIELDS)
CONFIG_DATA_START_ROW = 4


def status_column(commute: str) -> int:
    """実行状況の列番号（通勤用は Q 列、入寮用は P 列）。"""
    return len(CONFIG_FIELDS[commute]) + 1


@dataclass
class PlanRow:
    row: int          # 入稿予定表の行番号
    run_date: date | None
    company: str
    category: str     # 「1クルマ」など、実行設定の職種番号と同じ表記
    night: bool
    count: int
    commute: str = ""     # 通勤 / 入寮（空欄なら settings.json の schedule_default_commute）
    employment: str = ""  # 正社員 / 契約社員 など
    status: str = ""      # 公開 / 下書き
    title_choice: str = ""  # 6重め・7軽めの職種名選択（「7軽め｜防犯カメラの検査」または職種名だけ）
    standby_keyword: str = ""  # スタンバイキーワード（空欄なら GAS が自動で選ぶ）
    box_word: str = ""         # 求人ボックスワード（空欄なら settings.json の defaults）

    @property
    def key(self) -> str:
        d = self.run_date.isoformat() if self.run_date else "日付なし"
        return "|".join([str(self.row), d, self.company, self.category, "夜勤あり" if self.night else "夜勤なし",
                         str(self.count), self.commute, self.employment, self.status, self.title_choice,
                         self.standby_keyword, self.box_word])


def parse_date(s, today: date) -> date | None:
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        # スプレッドシートの日付のシリアル値（表示形式に関係なく、セルに入っている日付そのもの）
        return date(1899, 12, 30) + timedelta(days=int(s))
    s = str(s).strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})[/月](\d{1,2})日?", s)
    return date(today.year, int(m[1]), int(m[2])) if m else None


def read_plan(table: list[list[str]], today: date) -> list[PlanRow]:
    """入稿予定表（1行目が見出し）から、会社・職種・原稿数がそろった行を読む。

    実行日は表示形式で「11/2」のように見えていても正しく読めるよう、
    シートからは書式を当てない値（日付はシリアル値）で受け取る。
    """
    if not table:
        return []
    head = [header_name(h) for h in table[0]]
    col = {n: head.index(n) for n in ("実行日", "会社", "職種", "夜勤有無", "原稿数")}
    # あとから足した列。無ければ空欄として扱う
    for n in ("通勤/入寮", "雇用形態", "入稿ステータス", "職種名選択", "スタンバイキーワード", "求人ボックスワード"):
        if n in head:
            col[n] = head.index(n)
    rows = []
    for i, r in enumerate(table[1:], start=2):
        get = lambda n: str(r[col[n]]).strip() if n in col and col[n] < len(r) else ""
        if not (get("会社") and get("職種") and get("原稿数")):
            continue
        count = int(re.sub(r"[^\d]", "", get("原稿数")) or 0)
        raw_date = r[col["実行日"]] if col["実行日"] < len(r) else ""
        rows.append(PlanRow(i, parse_date(raw_date, today), get("会社"), get("職種"),
                            get("夜勤有無").upper() == "TRUE", count,
                            get("通勤/入寮"), employment_type(get("雇用形態")), get("入稿ステータス"),
                            get("職種名選択"), get("スタンバイキーワード"), get("求人ボックスワード")))
    return rows


def header_name(h) -> str:
    """見出し「職種名選択\n(6重め/7軽めのみ・必須)」→「職種名選択」。改行やかっこの補足を除く。"""
    s = str(h).strip().split("\n")[0]
    return re.split(r"[（(]", s)[0].strip()


def employment_type(s: str) -> str:
    """「正社員」→「正社員（人材紹介）」のように、実行設定（Q-mate）の表記にそろえる。"""
    s = s.strip()
    if not s or "（" in s or s == "その他":
        return s
    return f"{s}（人材紹介）"


def salary_pattern(category: str, night: bool, rules: dict, default: str) -> str:
    """給与下限の決まり（rules.json の salary_floor）から、GAS の給与パターン「35万」などを決める。"""
    job = re.sub(r"^\d+", "", category)
    floor = rules.get("salary_floor", {}).get(job, {}).get("夜勤あり" if night else "夜勤なし")
    return f"{floor // 10000}万" if floor else default


def commute_of(plan: PlanRow, default: str) -> str:
    """その行を通勤用・入寮用のどちらの GAS で作るか。"""
    c = plan.commute or default
    if c not in COMMUTE_TYPES:
        raise ValueError(f"通勤/入寮の値「{c}」が読めません（通勤 か 入寮 を入れてください）")
    return c


def config_row(plan: PlanRow, commute: str, target: dict, rules: dict, today: date, run_id: str,
               status: str | None = None, count: int | None = None) -> list:
    """実行設定に書く予約行。target は settings.json の schedule_targets の通勤・入寮のどちらか。"""
    defaults = target.get("defaults", {})
    if re.sub(r"^\d+", "", plan.category) in ("重め", "軽め") and not plan.title_choice:
        raise ValueError(f"{plan.category} は入稿予定表の「職種名選択」列に職種名を入れてください")
    pattern = defaults.get("給与パターン", "")
    if target.get("salary_from_floor"):
        pattern = salary_pattern(plan.category, plan.night, rules, pattern or "基本")
    v = {
        "グループ番号": f"予定{plan.row}_{run_id}-1",
        "作成日": today.strftime("%Y/%m/%d"),
        "通勤か入寮か": commute,
        "職種番号": plan.category,
        "会社名": plan.company,
        "原稿数": count or plan.count,
        "給与パターン": pattern,
        "夜勤の有無": "夜勤あり" if plan.night else "夜勤なし",
        "職種名選択": title_choice(plan),
    }
    for k, val in (("雇用形態", plan.employment), ("ステータス", status or plan.status),
                   ("スタンバイキーワード", plan.standby_keyword), ("求人ボックスワード", plan.box_word)):
        if val:
            v[k] = val
    for k in ("雇用形態", "更新種別", "ステータス", "画像カテゴリー", "スタンバイキーワード",
              "タイトル(施策)", "求人ボックスワード"):
        v.setdefault(k, defaults.get(k, ""))
    return [v[f] for f in CONFIG_FIELDS[commute]]


def title_choice(plan: PlanRow) -> str:
    """職種名選択を GAS のプルダウンと同じ「7軽め｜職種名」の形にそろえる。"""
    t = plan.title_choice.strip()
    if not t or "｜" in t:
        return t
    return f"{plan.category}｜{t}"


def output_sheets(status_text: str) -> list[str]:
    """実行状況「✅完了(…) 500件 → 出力_A, 出力_B」から出力シート名を取り出す。"""
    if "→" not in status_text:
        return []
    return [s.strip() for s in status_text.split("→", 1)[1].split(",") if s.strip()]


class GasRunner:
    """GAS のウェブアプリ（gas/qmate_agent_api.gs）に生成を頼む。"""

    def __init__(self, url: str, token: str):
        self.url, self.token = url, token

    def run(self) -> None:
        import requests

        try:
            r = requests.post(self.url, json={"token": self.token, "action": "run"}, timeout=400)
        except requests.Timeout:
            return  # GAS 側は動き続けているので、実行設定の実行状況を見て待つ
        try:
            body = r.json()
        except ValueError:
            raise RuntimeError(f"GAS の応答が読めません（HTTP {r.status_code}）。ウェブアプリの URL とアクセス設定を確認してください")
        if not body.get("ok"):
            raise RuntimeError(f"GAS がエラーを返しました: {body.get('error')}")


def wait_generated(book, row: int, col: int, timeout_s: int, interval_s: int, log) -> str:
    """実行設定の実行状況が完了かエラーになるまで待ち、その文言を返す。"""
    deadline = time.monotonic() + timeout_s
    while True:
        text = book.config_status(row, col)
        if text.startswith("✅") or text.startswith("❌"):
            return text
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{timeout_s // 60}分待っても生成が終わりませんでした（実行設定 {row}行目: {text or '空欄'}）")
        log(f"  生成を待っています（実行設定 {row}行目: {text or '待機中'}）")
        time.sleep(interval_s)
