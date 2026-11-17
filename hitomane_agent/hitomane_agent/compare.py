"""GAS で作った原稿とツールで作った原稿を、列ごとに見比べる（生成をツールに切り替える前の確認用）。

Q-mate 版（qmate_agent/qmate_agent/compare.py）と同じ見方。原稿の多くの列はランダムに選ばれるので、1件ずつは一致しない。
見るのは次の点。
  - 全部の原稿で同じ値の列（固定列など）が、両方で同じ値か
  - 片方だけ空欄、片方だけ毎回変わる、といった作りの違いがないか
  - 毎回変わる列は、値の形（数字を 9 に置き換えた形）と例を並べて、人が見て確かめる
"""
import re

from .checks import Manuscript


def _shape(v: str) -> str:
    return re.sub(r"\d", "9", v)


def compare(gas: Manuscript, tool: Manuscript) -> tuple[list[str], int]:
    """（結果の行, 違いがあった列の数）。"""
    lines, diff = [], 0
    if gas.headers != tool.headers:
        lines.append("✖ 見出しが違います（GAS と ツールで列の並びが違う）")
        diff += 1
    lines.append(f"原稿の数：GAS {len(gas.rows)}件 ／ ツール {len(tool.rows)}件")
    short = lambda v: (v[:60] + "…") if len(v) > 60 else v
    ex = lambda vs: next((v for v in vs if v), "")
    for h in [h for h in gas.headers if h]:
        gv = [r.get(h, "") for r in gas.rows]
        tv = [r.get(h, "") for r in tool.rows]
        gs, ts = set(gv), set(tv)
        if gs <= {""} and ts <= {""}:
            continue
        g_fixed, t_fixed = len(gs) == 1, len(ts) == 1
        if (gs <= {""}) != (ts <= {""}):
            diff += 1
            lines.append(f"✖ 片方だけ空欄　{h}: GAS={short(ex(gv))!r} ／ ツール={short(ex(tv))!r}")
        elif g_fixed and t_fixed:
            if gs == ts:
                lines.append(f"　同じ（固定）　{h}: {short(ex(gv))!r}")
            else:
                diff += 1
                lines.append(f"✖ 固定の値が違う　{h}: GAS={short(ex(gv))!r} ／ ツール={short(ex(tv))!r}")
        elif g_fixed != t_fixed:
            diff += 1
            which = "GAS は固定・ツールは毎回変わる" if g_fixed else "GAS は毎回変わる・ツールは固定"
            lines.append(f"✖ {which}　{h}: GAS={short(ex(gv))!r} ／ ツール={short(ex(tv))!r}")
        else:
            sg, st = {_shape(v) for v in gv}, {_shape(v) for v in tv}
            lines.append(f"　どちらも毎回変わる　{h}（同じ値 {len(gs & ts)}種類／形が同じ {len(sg & st)}種類）\n"
                         f"　　GAS の例: {short(ex(gv))!r}\n　　ツールの例: {short(ex(tv))!r}")
    return lines, diff
