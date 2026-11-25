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


# ---------------------------------------------------------------- 同じ日のお仕事番号を重ねない（2026-11-24 の Grit144811 から）

class Guard:
    """このパソコンで作ったお仕事番号を覚えておき、同じ番号を作らないようにする。

    同じお仕事番号で掲載期間が重なる原稿は、ヒトマネが「同じ拠点（またはお仕事番号）で掲載期間が重複する原稿があります」
    のエラーで取り込まない。2026-11-24 は条件が同じ行（夜勤あり・製造・高額）どうしで、給与・画像・市区町村がたまたま
    そろい 1件入らなかった。お仕事番号には作成日（yyMMdd）が入るので、同じ作成日の番号だけ見ればよい。
    記録は state/work_numbers_used.json（お仕事番号 → 募集番号）。古い日のものは読むときに捨てる。
    """
    FILE = "work_numbers_used.json"
    KEEP_DAYS = 14

    def __init__(self, used: dict | None = None, log=print):
        self.used = dict(used or {})
        self.log = log
        self.notes: list[str] = []

    @classmethod
    def load(cls, today=None, log=print) -> "Guard":
        import json
        from datetime import date, datetime, timedelta

        from . import config
        path = config.STATE_DIR / cls.FILE
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        oldest = (today or date.today()) - timedelta(days=cls.KEEP_DAYS)
        keep = {}
        for number, code in data.items():
            parts = str(number).split("-")
            try:
                made = datetime.strptime(parts[1], "%y%m%d").date()
            except (IndexError, ValueError):
                continue
            if made >= oldest:
                keep[number] = code
        return cls(keep, log)

    def save(self) -> None:
        import json

        from . import config
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        (config.STATE_DIR / self.FILE).write_text(json.dumps(self.used, ensure_ascii=False, indent=0), encoding="utf-8")

    def taken(self, number: str) -> bool:
        return bool(number) and number in self.used

    def add(self, number: str, code: str) -> None:
        if number:
            self.used[number] = code

    def pick(self, make, code: str, tries: int = 50):
        """make() で1件作り、お仕事番号が使用済みなら作り直す（make は呼ぶたびに画像・給与を選び直すもの）。

        make() は (行, お仕事番号) を返す。作り直したときと、作り直しても重なりが外れなかったときは知らせる。"""
        row, number = make()
        if not self.taken(number):
            self.add(number, code)
            return row
        first, other = number, self.used[number]
        for _ in range(tries):
            row, number = make()
            if not self.taken(number):
                self.add(number, code)
                self._note(f"お仕事番号が同じ日の原稿（{other}）と重なったので、{code} の画像・給与を選び直しました："
                           f"{first} → {number}")
                return row
        self.add(number, code)
        self._note(f"⚠ {code} のお仕事番号が同じ日の原稿（{other}）と重なっています。選び直しても外れませんでした"
                   f"（{number}）。このまま入稿すると、この1件はヒトマネで取り込めない場合があります")
        return row

    def _note(self, text: str) -> None:
        self.notes.append(text)
        if self.log:
            self.log(text)
