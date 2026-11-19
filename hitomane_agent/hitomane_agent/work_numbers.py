"""お仕事番号の登録用 CSV（お仕事情報管理の「ファイル取込予約」に入れるもの）。

ヒトマネの原稿の「お仕事番号」は、お仕事情報管理に登録してある番号から選ぶ欄で、登録していない番号の原稿を取り込むと
「お仕事番号が入力されていません」のエラーになる（2026-11-19 に GritMate で確認）。そこで、原稿を取り込む前に、
原稿のお仕事番号と拠点だけの CSV をお仕事情報管理へ取り込む。同じお仕事番号がすでにあれば上書きされる（画面の注意書き）。

CSV の形は、2026-11-19 にお仕事情報管理から取り出した実物と同じ：Shift_JIS・CRLF・値はすべて「"」で囲む・27列。
1列目 work_number がお仕事番号、2列目 m_branch が拠点の名前（原稿の「拠点」と同じ。例：GritMate株式会社）、残りは空欄。
"""
from .checks import Manuscript

HEADERS = ["work_number", "m_branch", "recruitment_budget", "sex", "age_lower_limit", "age_upper_limit", "experience",
           "skill", "required_qualification", "work_length", "wanted_persons", "location", "job_type", "salary",
           "contract_type", "contact_name1", "contact_name2"] + [f"note_{i}" for i in range(1, 11)]


def pairs(ms: Manuscript) -> list[tuple[str, str]]:
    """原稿のお仕事番号と拠点（同じお仕事番号は1つにまとめる。お仕事番号が空の行は入れない）。"""
    out = {}
    for r in ms.rows:
        number = str(r.get("お仕事番号") or "").strip()
        if number and number not in out:
            out[number] = str(r.get("拠点") or "").strip()
    return list(out.items())


def problem(items: list[tuple[str, str]]) -> str | None:
    """登録できない理由（拠点が空の行がある）。"""
    empty = [n for n, b in items if not b]
    if empty:
        return f"拠点が空のお仕事番号があります（{len(empty)}件。例：{empty[0]}）"
    return None


def _q(v: str) -> str:
    return '"' + str(v).replace('"', '""') + '"'


def to_csv_bytes(items: list[tuple[str, str]]) -> bytes:
    lines = [",".join(_q(h) for h in HEADERS)]
    for number, branch in items:
        lines.append(",".join(_q(v) for v in [number, branch] + [""] * (len(HEADERS) - 2)))
    return "".join(line + "\r\n" for line in lines).encode("cp932")
