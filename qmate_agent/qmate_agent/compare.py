"""GAS で作った原稿とツールで作った原稿を、列ごとに見比べる（生成をツールに切り替える前の確認用）。

原稿の多くの列はランダムに選ばれるので、1件ずつは一致しない。見るのは次の点。
  - 全部の原稿で同じ値の列（テンプレートなど）が、両方で同じ値か
  - 片方だけ空欄、片方だけ毎回変わる、といった作りの違いがないか
  - 毎回変わる列は、値の形（数字を 9 に置き換えた形）と例を並べて、人が見て確かめる
"""
import re

from .checks import base_name


def _shape(v: str) -> str:
    return re.sub(r"\d", "9", v)


def compare(gas, tool) -> tuple[list[str], int]:
    """2つの Manuscript を比べ、（結果の行, 違いがあった列の数）を返す。"""
    headers = [h for h in gas.headers if h]
    lines, diff = [], 0
    for h in headers:
        name = base_name(h)
        gv = [r.get(name, "") for r in gas.rows]
        tv = [r.get(name, "") for r in tool.rows]
        gs, ts = set(gv), set(tv)
        if gs <= {""} and ts <= {""}:
            continue
        g_fixed, t_fixed = len(gs) == 1, len(ts) == 1
        ex = lambda vs: next((v for v in vs if v), "")
        short = lambda v: (v[:60] + "…") if len(v) > 60 else v
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
            shapes_g, shapes_t = {_shape(v) for v in gv}, {_shape(v) for v in tv}
            common = len(ts & gs)
            lines.append(f"　どちらも毎回変わる　{h}（同じ値 {common}種類／形が同じ {len(shapes_g & shapes_t)}種類）\n"
                         f"　　GAS の例: {short(ex(gv))!r}\n　　ツールの例: {short(ex(tv))!r}")
    return lines, diff
