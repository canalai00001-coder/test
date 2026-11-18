"""施策の作り方（shisaku.py。＜ヒトマネ/施策用＞の GAS の③）。"""
import random
import unittest
from datetime import date, datetime

from hitomane_agent import checks, generator as g, shisaku
from hitomane_agent.headers import NEW_FORMAT, OLD_FORMAT
from tests import gen_samples as s

NOW = datetime(2026, 11, 20, 10, 0)
TODAY = NOW.date()
CB = "canal benefits株式会社"


def target(row=2, fmt="新FMT", category="5半導体", count=None, prefix="CB100", spec="", bunrui="", pref="", city="",
           salary="基本", night="夜勤あり", end_word="若手の先輩が在籍", company=CB, image="製造"):
    return g.Target(sheet_row=row, group_id=f"予定{row}", seq=1, creation_date="2026/11/20", commute="入寮",
                    employment="正社員", category=category, company=company, format=fmt, count=count,
                    count_raw="" if count is None else str(count), entry_prefix=prefix, status="掲載",
                    image_category=image, salary_pattern=salary, night_shift=night, paired_title="",
                    title_dedup_word=end_word, exec_status="", title_spec=spec, bunrui=bunrui, pref=pref, city=city)


def run(ts, base=None, **kw):
    base = base or s.shisaku_base()
    return base, shisaku.run(base, ts, s.bunrui_reader, seed=1, now=NOW, today=TODAY, **kw)


def as_dicts(res):
    return [dict(reversed(list(zip(res.headers, r)))) for r in res.rows]


class TestBase(unittest.TestCase):
    def test_title_words_and_images(self):
        base = s.shisaku_base()
        self.assertEqual(base.title, {"head": "急募", "f": ["最短入社", "即日入社可"], "h": ["寮費無料×即日勤務", "学歴不問×正社員"]})
        self.assertIn("転職サポート", base.bank.images_by_category)
        self.assertIn(f"社名入り_{CB}", base.bank.images_by_category)

    def test_local_records(self):
        base = shisaku.remember_local(s.shisaku_base(), {"locations": [[CB, "5半導体", "大阪府", "池田市", "半導体の製造A", "x"]]})
        self.assertEqual(base.loc_used[shisaku.loc_key(CB, "大阪府", "池田市")], {"半導体の製造A"})


class TestNewFormat(unittest.TestCase):
    def test_rows(self):
        base, [res] = run([target()])
        self.assertEqual(res.error, "")
        self.assertEqual(res.headers, NEW_FORMAT)
        self.assertEqual(res.name, f"ヒトマネ出力_施策_新_G予定2_{CB}_5半導体_20261120")
        rows = as_dicts(res)
        self.assertEqual(len(rows), 3)  # 原稿数が空欄 → NG エリア（沖縄県）を除いた勤務地の数
        self.assertEqual(sorted(r["勤務地_都道府県"] for r in rows), ["大阪府", "愛知県", "東京都"])
        self.assertEqual([r["募集番号"] for r in rows], ["CB100", "CB101", "CB102"])
        r = rows[0]
        self.assertEqual((r["画像名1"], r["画像名2"], r["画像名3"], r["画像名一覧用"]),
                         ("製造(1)", "転職(1)", "canal benefits株式会社(1)", "製造(1)"))
        self.assertRegex(r["募集職種"], r"^急募／半導体の製造[AB]／(最短入社|即日入社可)／(寮費無料×即日勤務|学歴不問×正社員)／若手の先輩が在籍$")
        self.assertTrue(r["仕事内容"].startswith("＼上の文／\n\n半導体のお仕事"))
        self.assertTrue(r["仕事内容"].endswith("＼下の文／\n\n" + shisaku.SMOKING_NOTE))
        self.assertTrue(r["お仕事番号"].startswith("3-261120-2-1-5-"))
        self.assertIn("-製造(1)-", r["お仕事番号"])
        self.assertEqual(r["勤務時間_開始_1"], "9:55")  # 夜勤ありの勤務時間シート
        # 勤務地ごとに、職種名を使用履歴に残す
        self.assertEqual(len(res.loc_records), 3)
        self.assertEqual(res.loc_records[0][:2], [CB, "5半導体"])
        # チェックを通る
        ms = checks.Manuscript("x", [res.headers] + res.rows)
        sheet, issues = checks.check_sheet(ms, __import__("hitomane_agent.config", fromlist=["load"]).load("rules.json"))
        self.assertEqual(sheet, [])
        self.assertFalse([i for r in issues for i in r if i.severity == "error"])

    def test_same_title_not_used_twice_at_a_place(self):
        used = [(CB, "5半導体", "大阪府", "池田市", "半導体の製造A", "2026-11-01 10:00")]
        base, [res] = run([target(pref="大阪府", city="池田市", count=1)], s.shisaku_base(loc_rows=used))
        self.assertEqual(as_dicts(res)[0]["募集職種"].split("／")[1], "半導体の製造B")
        # 2つとも使ったら作らない（同じ実行の中の前の行も数える）
        _, [res2] = run([target(row=3, pref="大阪府", city="池田市", count=1)], base)
        self.assertIn("大阪府池田市(1件必要／未使用の職種名は残り0件・1件不足)", res2.error)

    def test_place_filters(self):
        _, [res] = run([target(pref="東京都", count=1)])
        self.assertEqual([r["勤務地_市区町村"] for r in as_dicts(res)], ["葛飾区"])
        _, [res] = run([target(pref="沖縄県")])
        self.assertIn("この会社のNGエリア", res.error)
        _, [res] = run([target(city="葛飾区")])
        self.assertIn("勤務地_都道府県も選んで", res.error)

    def test_title_spec(self):
        _, [res] = run([target(spec="5半導体｜特別な職種", pref="東京都")])
        self.assertEqual(as_dicts(res)[0]["募集職種"].split("／")[1], "特別な職種")
        _, [res] = run([target(spec="特別な職種", count=6)])
        self.assertIn("1つの勤務地に作れるのは1件", res.error)

    def test_salary_man(self):
        _, [res] = run([target(salary="25万")])
        for r in as_dicts(res):
            lo, hi = int(r["基本給_最低額"]), int(r["基本給_最高額"])
            self.assertTrue(250000 <= lo <= 259999)
            self.assertEqual(hi, int(lo * 1.25 + 0.5))
            self.assertIn(str(lo), r["給与"])
            self.assertIn(str(hi), r["給与"])
        self.assertEqual(len({r["基本給_最低額"] for r in as_dicts(res)}), 3)

    def test_missing_company_images(self):
        _, [res] = run([target(company="株式会社エイトビィ")])
        self.assertIn("社名入り_株式会社エイトビィ", res.error)

    def test_continuation(self):
        cont = {}
        _, rs = run([target(row=2, count=1), target(row=3, prefix="", count=2)], continuation=cont)
        self.assertEqual([as_dicts(r)[0]["募集番号"] for r in rs], ["CB100", "CB101"])
        self.assertEqual(cont, {CB: "CB103"})


class TestOldFormat(unittest.TestCase):
    def test_rows(self):
        _, [res] = run([target(fmt="旧FMT", night="夜勤なし")])
        self.assertEqual(res.error, "")
        self.assertEqual(res.headers, OLD_FORMAT)
        self.assertEqual(res.name, f"ヒトマネ出力_施策_G予定2_{CB}_5半導体_20261120")
        row = res.rows[0]
        self.assertEqual(len(row), 109)
        first, second = [i for i, h in enumerate(OLD_FORMAT) if h == "応募方法"]
        self.assertEqual(row[first], "電話とWEB")
        self.assertEqual(row[second], "＜応募方法＞WEB\n＜応募方法2つ目＞")
        r = as_dicts(res)[0]
        self.assertEqual((r["シフト"], r["早朝"], r["媒体"]), ("週5日以上", "TRUE", "自社"))
        self.assertEqual(r["勤務時間"], "夜勤なしの勤務時間")
        self.assertEqual(r["勤務地"], r["都道府県"] + r["市区町村"])
        self.assertEqual(r["一覧用給与"], r["給与"])
        self.assertEqual(r["最低給与額"], "")
        ms = checks.Manuscript("x", [res.headers] + res.rows)
        self.assertTrue(ms.is_old_format)
        self.assertEqual(ms.rows[0]["応募方法"], "電話とWEB")  # 同じ見出しは1つ目
        from hitomane_agent import config
        sheet, issues = checks.check_sheet(ms, config.load("rules.json"))
        self.assertEqual(sheet, [])
        self.assertFalse([i for r in issues for i in r if i.severity == "error"])
        # CSV（Shift_JIS）にすると109列（「応募方法」は2つ）
        from hitomane_agent.csv_export import to_csv_bytes
        head = to_csv_bytes(ms).decode("cp932").split("\r\n")[0].split(",")
        self.assertEqual(len(head), 109)
        self.assertEqual(head.count("応募方法"), 2)


class TestBunrui(unittest.TestCase):
    def test_heavy_light(self):
        _, [res] = run([target(category="7軽め", bunrui="手のひら", count=2)])
        self.assertEqual(res.error, "")
        rows = as_dicts(res)
        titles = sorted(r["募集職種"].split("／")[1] for r in rows)
        self.assertEqual(titles, ["グラスの検品", "メガネケースの検査"])  # 仕事内容の無い職種は使わない
        for r in rows:
            letter = "A" if "グラス" in r["募集職種"] else "B"
            self.assertIn(f"-7{letter}-", r["お仕事番号"])

    def test_needs_bunrui(self):
        _, [res] = run([target(category="7軽め")])
        self.assertIn("「分類」の選択が必須", res.error)

    def test_spec_from_other_sheet(self):
        _, [res] = run([target(category="7軽め", bunrui="手のひら", spec="倉庫の仕分け", pref="東京都")])
        self.assertEqual(as_dicts(res)[0]["募集職種"].split("／")[1], "倉庫の仕分け")
        _, [res] = run([target(category="7軽め", bunrui="手のひら", spec="無い職種")])
        self.assertIn("重め軽め職種分類に見つかりません", res.error)

    def test_no_reader(self):
        base = s.shisaku_base()
        [res] = shisaku.run(base, [target(category="7軽め", bunrui="手のひら")], None, seed=1, now=NOW, today=TODAY)
        self.assertIn("重め軽め職種分類 を読めません", res.error)


class TestTitle(unittest.TestCase):
    def test_deck_and_not_seishain(self):
        base = s.shisaku_base()
        rnd = random.Random(0)
        words = [shisaku.draw_word(base, "F", base.title["f"], "正社員", rnd) for _ in range(4)]
        self.assertEqual(sorted(words[:2]), sorted(base.title["f"]))  # 1周するまで同じ語は出ない
        self.assertEqual(shisaku.draw_word(base, "H", base.title["h"], "契約社員", rnd), "寮費無料×即日勤務")

    def test_too_long(self):
        _, [res] = run([target(end_word="あ" * 90)])
        self.assertIn("100文字を超えました", res.error)


if __name__ == "__main__":
    unittest.main()
