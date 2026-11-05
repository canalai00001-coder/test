"""原稿の生成（GAS から移した処理）を確かめる。土台のシートは実際の作りに合わせて再現している。"""
import random
import re
import unittest
from datetime import date, datetime

from qmate_agent import generator as g
from qmate_agent.qmate_headers import QMATE_HEADERS

NOW = datetime(2026, 11, 5, 10, 0)


def base_sheets():
    template = [QMATE_HEADERS, [""] * len(QMATE_HEADERS)]
    template[1][QMATE_HEADERS.index("キーワードリスト（複数選択可）")] = "製造,寮・社宅あり"
    template[1][QMATE_HEADERS.index("性別制限|必須")] = "なし"
    return [
        ("原稿確認(川名)", lambda: [["読んではいけない"]]),
        ("職種名", lambda: [["1クルマ", "2工場", "3軽作業", "5半導体"],
                           ["くるまの製造スタッフ", "工場スタッフ", "軽作業", "半導体"],
                           ["車関係の製造作業スタッフ", "", "", ""]]),
        ("会社情報", lambda: [["会社情報マスター入力シート"], ["※ 3行目以降"], ["※ 黄色"], [],
                             ["会社名", "応募時メール送信先1", "有料職業紹介業許可番号", "仕事内容の後に入れる項目",
                              "会社所在地_住所", "応募受付完了メール件名", "応募受付完了メール本文", "求人メモ用会社名"],
                             ["AspiRove株式会社", "aspi@example.com", "33-ユ-300395", "本求人は、AspiRove株式会社…",
                              "岡山県倉敷市", "件名", "本文", "AspiRove株式会社/G"]]),
        ("給与", lambda: [["最低額", "月給下限", "", "最高額", "月給上限", "低額", "", "基本給_最低額", "月給下限", "", "基本給_最高額",
                          "月給上限", "基本", "", "基本給_最低額", "月給下限", "", "基本給_最高額", "月給上限", "高額", "",
                          "給与（詳細）\n正社員"],
                         ["250000円～320000円"], ["給与_下限", "", "", "給与_上限"],
                         [250000, "250000円", "-", 312500, "312500円", "給与\n月給　250000円‐312500円", "",
                          317190, "317190円", "-", 396488, "396488円", "＜　月給　＞　317190円 ‐ 396488円", "",
                          351100, "351100円", "-", 438875, "438875円", "---月給---", "", "【給与】\n月給　円‐　円"],
                         ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
                          "＜月給＞\n　万円‐　万円"],
                         ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "給与　円-　円"]]),
        ("原稿勤務地・NG勤務地", lambda: [["", "都道府県", "市区町村", "合体(D3に関数あり)", "", "AspiRove", "ArK"],
                                       ["1", "愛知県", "岡崎市", "愛知県岡崎市", "", "沖縄県", "沖縄県"],
                                       ["2", "愛知県", "刈谷市", "愛知県刈谷市", "", "", ""],
                                       ["3", "沖縄県", "那覇市", "沖縄県那覇市", "", "", ""],
                                       ["4", "岡山県", "倉敷市", "岡山県倉敷市", "", "", ""],
                                       ["5", "愛知県", "岡崎市", "愛知県岡崎市", "", "", ""]]),
        ("タイトル", lambda: [["", "", "", "", "", "職種名"], [], ["", "スタンバイタイトル", "", "", "2000"],
                             ["1", "＜ガッツリ稼ぐ＞", "", "1", "「20代の社員在籍」", "x", "／", "二交代", "／", "新生活サポートあり", "／", "稼いで遊べる"],
                             ["2", "＜かんたん系＞", "", "2", "「若手スタッフ在籍」", "x", "／", "二交代", "／", "住み込みOK", "／", "稼いで遊べる"]]),
        ("タイトル(施策)", lambda: [["", "", "", "", "", "", "固定", "", "待遇", "", "固定２"], [], [],
                                 ["1", "", "", "", "", "", "年間休日120日", "", "交通費支給", "", "20代活躍"],
                                 ["2", "", "", "", "", "", "急募", "", "寮完備", "", "未経験OK"]]),
        ("応募資格・勤務時間・休日・キャッチコピー・待遇", lambda: [
            ["", "キャッチコピー", "応募資格・条件|必須", "選考フロー", "勤務時間|必須\n夜勤あり", "勤務時間|必須\n夜勤あり　2時３時",
             "勤務時間|必須\n夜勤なし", "待遇・福利厚生\n(正社員)", "待遇・福利厚生\n(正社員)", "休日休暇"],
            ["", "", "＜2000＞\n4000文字までOK", "", "", "", "", "", "", ""],
            ["1", "キャッチ1", "資格1", "フロー1", "夜勤あり1", "2時3時1", "夜勤なし1", "古い待遇", "待遇1", "休日1"],
            ["2", "キャッチ2", "資格2", "フロー2", "夜勤あり2", "", "夜勤なし2", "", "待遇2", "休日2"]]),
        ("画像", lambda: [["画像カテゴリー", "製造", "軽作業"], ["職種", "・クルマ ・工場", "・軽め ・梱包"],
                         ["", 101, 201], ["", 102, ""]]),
        ("1クルマ", lambda: [["仕事内容"], ["クルマ仕事A", "クルマ仕事B"], ["クルマ仕事C"]]),
        ("7軽め", lambda: [["職種名", "アルファベット", "", "仕事内容"],
                          ["チョークの製造", "A", "", "軽め1", "軽め2"], ["石鹸の検査", "B", "", "軽め3"]]),
        ("12シール貼り", lambda: (_ for _ in ()).throw(AssertionError("要らないカテゴリは読まない"))),
        ("テンプレート(固定列)", lambda: template),
        ("スタンバイキーワード(自動集計)", lambda: [["カテゴリ", "順位", "キーワード"], ["1クルマ", 1, "挑戦するなら今"],
                                                   ["1クルマ", 2, "高収入寮付"], ["2工場", "-", "（該当キーワードなし）"]]),
    ]


def bank(cats=("クルマ", "軽め")):
    return g.load_bank(base_sheets(), set(cats))


class TestBank(unittest.TestCase):
    def test_roles_and_contents(self):
        b = bank()
        self.assertEqual(b.job_titles["1クルマ"], ["くるまの製造スタッフ", "車関係の製造作業スタッフ"])
        self.assertEqual(b.job_contents["クルマ"], ["クルマ仕事A", "クルマ仕事B", "クルマ仕事C"])
        self.assertEqual(b.paired["軽め"][0], {"title": "チョークの製造", "letter": "A", "contents": ["軽め1", "軽め2"]})
        self.assertEqual(b.companies["AspiRove株式会社"]["応募時メール送信先1"], "aspi@example.com")
        self.assertEqual(b.locations, [("愛知県", "岡崎市"), ("愛知県", "刈谷市"), ("沖縄県", "那覇市"), ("岡山県", "倉敷市")])
        self.assertEqual(b.ng_by_company["AspiRove"], ["沖縄県"])
        self.assertEqual(b.salary_patterns["基本"][0], {"lower": "317190", "upper": "396488", "detail": "＜　月給　＞　317190円 ‐ 396488円"})
        self.assertEqual(b.salary_detail_templates, ["【給与】\n月給　円‐　円", "給与　円-　円"])
        self.assertEqual(b.parts["待遇・福利厚生\n(正社員)"], ["待遇1", "待遇2"])  # 右の列だけ
        self.assertEqual(b.parts["応募資格・条件|必須"], ["資格1", "資格2"])     # 注記の行は読まない
        self.assertEqual(b.images_by_category, {"製造": ["101", "102"], "軽作業": ["201"]})
        self.assertEqual(b.image_category_by_job["クルマ"], "製造")
        self.assertEqual(b.personas, ["「20代の社員在籍」", "「若手スタッフ在籍」"])
        self.assertEqual(b.dedup_word, "稼いで遊べる")
        self.assertEqual(b.measure2, {"fixed1": ["年間休日120日", "急募"], "benefit": ["交通費支給", "寮完備"],
                                      "fixed2": ["20代活躍", "未経験OK"]})
        self.assertEqual(b.standby_keywords["クルマ"], ["挑戦するなら今", "高収入寮付"])
        self.assertEqual(b.fixed_template["キーワードリスト（複数選択可）"], "製造,寮・社宅あり")


def req(**kw):
    base = dict(category="1クルマ", company="AspiRove株式会社", count=3, salary_pattern="35万", night="夜勤あり",
                created=date(2026, 11, 5), title_measure="タイトル1(従来)", box_word="")
    base.update(kw)
    return g.Request(**base)


class TestGenerate(unittest.TestCase):
    def gen(self, usage=None, seed=1):
        return g.Generator(bank(), usage or [], rng=random.Random(seed), now=NOW)

    def test_commute_rows(self):
        r = self.gen().generate(req())
        self.assertEqual(len(r.rows), 3)
        places = [(x["勤務地：都道府県|必須"], x["勤務地：市区町村|必須"]) for x in r.rows]
        self.assertEqual(len(set(places)), 3)
        self.assertNotIn("沖縄県", [p for p, _ in places])  # NG の勤務地は使わない
        lows = [int(x["給与_下限"]) for x in r.rows]
        self.assertTrue(all(350000 <= v <= 359999 for v in lows))
        self.assertEqual(len(set(lows)), 3)
        for x in r.rows:
            lo, hi = int(x["給与_下限"]), int(x["給与_上限"])
            self.assertEqual(hi, g.js_round(lo * 1.25))
            self.assertEqual(x["基本給|▲必須"], x["給与_下限"])
            self.assertIn(f"{lo}円", x["詳細な給与情報"])
            self.assertRegex(x["職種名|必須"], r"^＜.+＞二交代・夜勤あり・挑戦するなら今$")
            self.assertLessEqual(g.js_len(x["求人ボックス用職種名"]), 50)
            self.assertTrue(x["求人ボックス用職種名"].endswith("／稼いで遊べる"))
            self.assertIn(x["求人ページ用画像1"], ("101", "102"))
            self.assertIn(x["勤務時間|必須"], ("夜勤あり1", "夜勤あり2"))
            self.assertIn(x["待遇・福利厚生"], ("待遇1", "待遇2"))
            self.assertTrue(x["仕事内容|必須"].endswith("\n\n本求人は、AspiRove株式会社…"))
            self.assertTrue(x["選考フロー"].endswith("【会社所在地】\n岡山県倉敷市"))
            self.assertEqual((x["ステータス|必須"], x["掲載企業名|必須"], x["採用担当者名"]), ("公開", "非公開", "採用担当"))
            self.assertEqual(x["キーワードリスト（複数選択可）"], "製造,寮・社宅あり")
            self.assertEqual(x["職種カテゴリー(中分類)|必須"], "工作機械・機械オペレーター・溶接工")
            self.assertEqual(x["給与形態に応じた労働時間（日給・週給・月給・年俸のみ）|▲必須"], "160")
            self.assertRegex(x["メモ"], rf"^22-261105-1-1-1-{lo}-{hi}-10[12]-{x['勤務地：都道府県|必須']}{x['勤務地：市区町村|必須']}-AspiRove株式会社/G$")
        self.assertEqual(sum(r.title_counts.values()), 3)

    def test_night_none_and_pattern(self):
        r = self.gen().generate(req(night="夜勤なし", salary_pattern="基本", standby_keyword="急募"))
        x = r.rows[0]
        self.assertIn(x["勤務時間|必須"], ("夜勤なし1", "夜勤なし2"))
        self.assertTrue(x["職種名|必須"].endswith("二交代・夜勤なし・急募"))
        self.assertEqual((x["給与_下限"], x["給与_上限"]), ("317190", "396488"))

    def test_variant_night_shift(self):
        x = self.gen().generate(req(night="夜勤あり(2時3時)")).rows[0]
        self.assertEqual(x["勤務時間|必須"], "2時3時1")

    def test_measure2_title(self):
        for x in self.gen().generate(req(title_measure="タイトル2(施策)", box_word="遠方からの応募可能")).rows:
            t = x["求人ボックス用職種名"]
            self.assertTrue(t.startswith("「") and "」二交代・夜勤あり／" in t and t.endswith("／遠方からの応募可能"))
            self.assertTrue("交通費支給" in t or "寮完備" in t)
            self.assertLessEqual(g.js_len(t), 50)

    def test_count_none_uses_location_count(self):
        self.assertEqual(len(self.gen().generate(req(count=None)).rows), 3)

    def test_paired_category(self):
        r = self.gen().generate(req(category="7軽め", title_choice="7軽め｜チョークの製造", salary_pattern="基本"))
        x = r.rows[0]
        self.assertIn(x["仕事内容|必須"].split("\n\n")[0], ("軽め1", "軽め2"))
        self.assertRegex(x["メモ"], r"^22-261105-1-1-7A-")
        self.assertEqual(r.title_counts, {"チョークの製造": 3})
        with self.assertRaises(ValueError):
            self.gen().generate(req(category="7軽め", title_choice=""))

    def test_cooldown(self):
        usage = [["AspiRove株式会社", "7軽め", "チョークの製造", 1, 30, "2026-11-01 10:00", 30, 30]]
        with self.assertRaises(ValueError):
            self.gen(usage).generate(req(category="7軽め", title_choice="チョークの製造"))
        self.gen(usage).generate(req(category="7軽め", title_choice="チョークの製造"), ignore_cooldown=True)
        old = [["AspiRove株式会社", "7軽め", "チョークの製造", 1, 30, "2026-09-01 10:00", 30, 30]]
        self.gen(old).generate(req(category="7軽め", title_choice="チョークの製造"))
        # 通常カテゴリは、30日以内に使った職種名を外して作る
        used = [["AspiRove株式会社", "1クルマ", "くるまの製造スタッフ", 1, 3, "2026-11-04 10:00", 3, 3]]
        r = self.gen(used).generate(req())
        self.assertEqual(set(r.title_counts), {"車関係の製造作業スタッフ"})

    def test_unknown_company(self):
        with self.assertRaises(ValueError):
            self.gen().generate(req(company="知らない会社"))

    def test_update_usage(self):
        rows = g.update_usage([["AspiRove株式会社", "1クルマ", "x", 2, 10, "2026-10-01 10:00", 5, 5]], "AspiRove株式会社",
                              "1クルマ", {"x": 3, "y": 4}, NOW)
        self.assertEqual(rows[0][3:8], [3, 13, "2026-11-05 10:00", 3, 3])
        self.assertEqual(rows[1], ["AspiRove株式会社", "1クルマ", "y", 1, 4, "2026-11-05 10:00", 4, 4])

    def test_js_round(self):
        # 350002 × 1.25 = 437502.5。GAS（Math.round）は 437503
        self.assertEqual(g.js_round(350002 * 1.25), 437503)
        self.assertEqual(g.js_round(2.4), 2)

    def test_usage_serial_date(self):
        self.assertEqual(g.parse_usage_date(46331.5), datetime(2026, 11, 5, 12, 0))


if __name__ == "__main__":
    unittest.main()
