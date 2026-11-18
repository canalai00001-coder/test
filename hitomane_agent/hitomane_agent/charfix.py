"""ツールで原稿を作るときに、取り込み用の CSV（Shift_JIS・cp932）で書けない記号を、似た記号に置き換える。

置き換えるのは、土台（通常・施策用）と ＜ヒトマネ＞重め軽め職種分類 にあった記号（2026-11-18 に全部のシートを調べた）。
表にない書けない文字は置き換えずに残し、チェックで NG にして知らせる（気づかないうちに文が変わらないように）。
GAS で作ったシートや、取り込む CSV そのものは変えない（作るときだけ）。
"""
import re

REPLACE = {
    # 行頭の印
    "▶": "■", "▷": "□", "▪": "・", "⠿": "・", "◉": "◎", "🔲": "□",
    # チェックの印
    "✔": "○", "✓": "○", "☑": "○",
    # 飾り
    "♦": "◆", "✦": "◆", "❖": "◆", "✧": "◇", "✚": "＋", "‼": "！！",
    # 線・かっこ・波線
    "═": "━", "—": "―", "–": "‐", "∼": "～", "｟": "《", "｠": "》",
}
# 消すもの（異体字セレクタ・ゼロ幅接合子・国旗の文字）
DROP = re.compile("[︎️‍\U0001F1E6-\U0001F1FF]")
_TABLE = str.maketrans(REPLACE)


def fix(text: str, counts: dict | None = None) -> str:
    """書けない記号を置き換えた文。counts を渡すと「▶→■」ごとの数を足す。"""
    if not isinstance(text, str) or text.isascii():
        return text
    if counts is not None:
        for ch in text:
            if ch in REPLACE:
                key = f"{ch}→{REPLACE[ch]}"
                counts[key] = counts.get(key, 0) + 1
        for m in DROP.findall(text):
            key = f"U+{ord(m):04X}→（消す）"
            counts[key] = counts.get(key, 0) + 1
    return DROP.sub("", text.translate(_TABLE))


def fix_rows(rows: list[list]) -> tuple[list[list], dict]:
    counts: dict = {}
    return [[fix(v, counts) for v in r] for r in rows], counts


def summary(counts: dict) -> str:
    return "、".join(f"{k} {v}か所" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
