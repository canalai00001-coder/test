"""入稿予定表の行から、原稿の生成・チェック・入稿までを1回で行う。

入稿予定表の1行 → 実行設定に予約行を追加 → GAS（ウェブアプリ）に生成を頼む
→ 実行設定の実行状況が「✅完了」になるまで待つ → 出力シートをチェック → Q-mate に入稿
"""
import re
import time
from dataclasses import dataclass
from datetime import date, datetime

# 実行設定シートの列（GAS の CONFIG_COLUMNS と同じ並び。A〜P 列に書き、Q 列の実行状況を読む）
CONFIG_FIELDS = [
    "グループ番号", "作成日", "通勤か入寮か", "雇用形態", "職種番号", "会社名", "原稿数", "更新種別",
    "ステータス", "画像カテゴリー", "給与パターン", "夜勤の有無", "スタンバイキーワード", "タイトル(施策)",
    "求人ボックスワード", "職種名選択",
]
CONFIG_STATUS_COL = 17  # Q列
CONFIG_DATA_START_ROW = 4


@dataclass
class PlanRow:
    row: int          # 入稿予定表の行番号
    run_date: date | None
    company: str
    category: str     # 「1クルマ」など、実行設定の職種番号と同じ表記
    night: bool
    count: int

    @property
    def key(self) -> str:
        d = self.run_date.isoformat() if self.run_date else "日付なし"
        return f"{self.row}|{d}|{self.company}|{self.category}|{'夜勤あり' if self.night else '夜勤なし'}|{self.count}"


def parse_date(s: str, today: date) -> date | None:
    s = s.strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})[/月](\d{1,2})日?", s)
    return date(today.year, int(m[1]), int(m[2])) if m else None


def read_plan(table: list[list[str]], today: date) -> list[PlanRow]:
    """入稿予定表（1行目が見出し）から、会社・職種・原稿数がそろった行を読む。"""
    if not table:
        return []
    head = [h.strip() for h in table[0]]
    col = {n: head.index(n) for n in ("実行日", "会社", "職種", "夜勤有無", "原稿数")}
    rows = []
    for i, r in enumerate(table[1:], start=2):
        get = lambda n: r[col[n]].strip() if col[n] < len(r) else ""
        if not (get("会社") and get("職種") and get("原稿数")):
            continue
        count = int(re.sub(r"[^\d]", "", get("原稿数")) or 0)
        rows.append(PlanRow(i, parse_date(get("実行日"), today), get("会社"), get("職種"),
                            get("夜勤有無").upper() == "TRUE", count))
    return rows


def salary_pattern(category: str, night: bool, rules: dict, default: str) -> str:
    """給与下限の決まり（rules.json の salary_floor）から、GAS の給与パターン「35万」などを決める。"""
    job = re.sub(r"^\d+", "", category)
    floor = rules.get("salary_floor", {}).get(job, {}).get("夜勤あり" if night else "夜勤なし")
    return f"{floor // 10000}万" if floor else default


def config_row(plan: PlanRow, defaults: dict, rules: dict, today: date, run_id: str,
               status: str | None = None, count: int | None = None) -> list:
    if re.sub(r"^\d+", "", plan.category) in ("重め", "軽め"):
        raise ValueError(f"{plan.category} は GAS で職種名の選択が必要なため、まだ自動実行できません")
    v = {
        "グループ番号": f"予定{plan.row}_{run_id}-1",
        "作成日": today.strftime("%Y/%m/%d"),
        "職種番号": plan.category,
        "会社名": plan.company,
        "原稿数": count or plan.count,
        "給与パターン": salary_pattern(plan.category, plan.night, rules, defaults.get("給与パターン", "基本")),
        "夜勤の有無": "夜勤あり" if plan.night else "夜勤なし",
    }
    for k in ("通勤か入寮か", "雇用形態", "更新種別", "ステータス", "画像カテゴリー", "スタンバイキーワード",
              "タイトル(施策)", "求人ボックスワード"):
        v.setdefault(k, defaults.get(k, ""))
    if status:
        v["ステータス"] = status
    v["職種名選択"] = ""
    return [v[f] for f in CONFIG_FIELDS]


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


def wait_generated(book, row: int, timeout_s: int, interval_s: int, log) -> str:
    """実行設定の実行状況が完了かエラーになるまで待ち、その文言を返す。"""
    deadline = time.monotonic() + timeout_s
    while True:
        text = book.config_status(row)
        if text.startswith("✅") or text.startswith("❌"):
            return text
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{timeout_s // 60}分待っても生成が終わりませんでした（実行設定 {row}行目: {text or '空欄'}）")
        log(f"  生成を待っています（実行設定 {row}行目: {text or '待機中'}）")
        time.sleep(interval_s)
