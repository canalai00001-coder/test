"""原稿の生成（ヒトマネ用 GAS の③の新FMT を移したもの）。"""
import unittest
from datetime import date, datetime

from hitomane_agent import generator as g
from hitomane_agent.headers import NEW_FORMAT
from tests import gen_samples as s

NOW = datetime(2026, 11, 17, 12, 0)


def run(rows, usage=None, only=None, seed=1):
    bank = g.build_bank(s.grids())
    return g.run(bank, usage or s.usage(), g.read_targets(s.CONFIG_HEAD + rows), only_groups=only, seed=seed,
                 now=NOW, today=NOW.date())


class TestBank(unittest.TestCase):
    def setUp(self):
        self.bank = g.build_bank(s.grids())

    def test_roles_like_sheet_diagnosis(self):
        self.assertEqual(self.bank.roles, {
            "会社情報": "会社情報マスター", "原稿勤務地・NG勤務地": "勤務地・NGエリア",
            "応募資格・勤務時間・休日・PR": "パーツ(PR等・正社員)", "給与": "給与パターン", "職種名": "職種名",
            "5半導体": "仕事内容(半導体)", "7軽め": "職種内容ペア(軽め)", "画像": "画像カテゴリー一覧",
            "タイトル": "組み立てタイトル(募集職種用)", "勤務時間(二交代/夜勤あり)": "勤務時間パターン(新FMT用・夜勤あり)",
            "勤務時間(二交代/夜勤なし)": "勤務時間パターン(新FMT用・夜勤なし)"})

    def test_quirks_are_kept(self):
        # GAS と同じく、仕事内容のシートは見出しの「仕事内容」も候補に入り、給与は4行目から読む
        self.assertIn("仕事内容", self.bank.job_contents["半導体"])
        self.assertEqual(self.bank.salary_patterns["低額"], [{"lower": "261400", "upper": "326750",
                                                             "detail": "【給与】月収 261400円‐326750円"}])
        self.assertEqual(self.bank.salary_patterns["高額"][0]["upper"], "")

    def test_parts_and_companies(self):
        self.assertEqual(self.bank.parts["PR\n(正社員)"], ["PRの文"])
        self.assertEqual(self.bank.companies["canal benefits株式会社"]["応募方法#2"], "＜応募方法2つ目＞")
        self.assertEqual(self.bank.paired_job_data["軽め"][0], {"title": "グラスの検品", "letter": "A",
                                                             "contents": ["グラスのお仕事1", "グラスのお仕事2"]})
        self.assertEqual(self.bank.title_components, {"personas": ["未経験入社組が在籍"], "appeals": ["新生活サポートあり"],
                                                      "dedup_word": "稼いで遊べる"})

    def test_ng_area(self):
        places = [l["pref"] + l["city"] for l in g.usable_locations(self.bank, "canal benefits株式会社")]
        self.assertEqual(places, ["愛知県みよし市", "大阪府池田市", "東京都葛飾区"])  # 沖縄県は NG
        # 会社名が NG の列名を含むとき（株式会社エイトビィ → エイトビィ）
        self.assertNotIn("大阪府池田市", [l["pref"] + l["city"] for l in g.usable_locations(self.bank, "株式会社エイトビィ")])


class TestGenerate(unittest.TestCase):
    def test_row_matches_gas(self):
        res = run([s.plan_row("1-1", count="2", prefix="CB97595")])[0]
        self.assertEqual((res.error, res.name), ("", "ヒトマネ出力_新_G1_canal benefits株式会社_5半導体_20261120"))
        r = res.rows[0]
        self.assertEqual(set(r), set(NEW_FORMAT))
        self.assertEqual([x["募集番号"] for x in res.rows], ["CB97595", "CB97596"])
        self.assertEqual((r["開始日"], r["終了日"], r["ステータス"]), ("2026/11/20", "2027/11/20", "掲載"))
        self.assertEqual(r["募集職種"], "「半導体の製造A」未経験入社組が在籍／二交代・夜勤あり／新生活サポートあり／稼いで遊べる")
        self.assertEqual((r["基本給_最低額"], r["基本給_最高額"]), ("320700", "400875"))
        self.assertEqual((r["勤務時間_開始_1"], r["休憩時間_1"], r["平均所定労働時間"]), ("9:55", "60", "160"))
        self.assertEqual((r["拠点コード"], r["拠点"], r["受付電話番号"]), ("B001", "CB株式会社", "06-4400-7510"))
        self.assertEqual(r["応募方法_補足"], "＜応募方法＞WEB\n＜応募方法2つ目＞")
        self.assertTrue(r["仕事内容"].endswith("\n\n【受動喫煙対策】受動喫煙対策あり（屋内禁煙）"))
        place = r["勤務地_都道府県"] + r["勤務地_市区町村"]
        self.assertEqual((r["地図用住所"], r["勤務地_補足"]), (place, place))
        self.assertEqual(r["お仕事番号"], f"3-261120-1-1-5-320700-400875-製造(1)-{place}-canal benefits株式会社")
        self.assertEqual(r["画像名一覧用"], "製造(1)")
        self.assertEqual(r["平日のみOK"], "なし")

    def test_blank_count_uses_all_locations_without_repeats(self):
        res = run([s.plan_row("1-1", count="", prefix="CB1")])[0]
        places = [r["勤務地_都道府県"] + r["勤務地_市区町村"] for r in res.rows]
        self.assertEqual(sorted(places), ["大阪府池田市", "愛知県みよし市", "東京都葛飾区"])

    def test_entry_number_continues_over_rows_and_groups(self):
        rows = [s.plan_row("1-1", count="2", prefix="CB0098"), s.plan_row("1-2", count="2"),
                s.plan_row("2-1", count="1")]
        res = run(rows)
        self.assertEqual([r["募集番号"] for r in res[0].rows], ["CB0098", "CB0099", "CB0100", "CB0101"])
        self.assertEqual(res[0].name, "ヒトマネ出力_新_G1_canal benefits株式会社_5半導体_20261120")
        # 1グループ目で職種名を2つとも使ったので、GAS と同じく2グループ目は「使い切り」で止まる
        self.assertIn("使い切りました", res[1].error)
        res = run(rows, only={"2"})  # 2グループ目だけ作るときも、前の番号は引き継ぐ
        self.assertEqual([r["募集番号"] for r in res[0].rows], ["CB0102"])

    def test_only_one_group_still_counts_earlier_numbers(self):
        rows = [s.plan_row("1-1", count="", prefix="CB10"), s.plan_row("2-1", count="2")]
        res = run(rows, only={"2"})
        self.assertEqual([r.group_id for r in res], ["2"])
        self.assertEqual([r["募集番号"] for r in res[0].rows], ["CB13", "CB14"])  # 1-1 は勤務地数の3件

    def test_titles_rotate_and_avoid_recent(self):
        recent = s.usage([["canal benefits株式会社", "5半導体", "半導体の製造A", "1", "3", "2026-11-10 10:00"]])
        res = run([s.plan_row("1-1", count="3", prefix="CB1")], usage=recent)[0]
        self.assertTrue(all("半導体の製造B" in r["募集職種"] for r in res.rows))

    def test_all_titles_used_stops(self):
        used = s.usage([["canal benefits株式会社", "5半導体", t, "1", "1", "2026-01-01 10:00"]
                        for t in ("半導体の製造A", "半導体の製造B")])
        res = run([s.plan_row("1-1", prefix="CB1")], usage=used)[0]
        self.assertIn("全2件)を全て使い切りました", res.error)

    def test_paired_category(self):
        res = run([s.plan_row("1-1", category="7軽め", count="2", prefix="CB1", paired="7軽め｜グラスの検品")])[0]
        self.assertEqual(res.error, "")
        self.assertTrue(res.rows[0]["お仕事番号"].startswith("3-261120-1-1-7A-"))
        self.assertIn(res.rows[0]["仕事内容"].split("\n")[0], ["グラスのお仕事1", "グラスのお仕事2"])

    def test_paired_used_title_stops_like_gas(self):
        used = s.usage([["canal benefits株式会社", "7軽め", "グラスの検品", "1", "1", "2025-01-01 10:00"]])
        rows = [s.plan_row("1-1", category="7軽め", prefix="CB1", paired="7軽め｜グラスの検品"), s.plan_row("2-1")]
        res = run(rows, usage=used)
        self.assertEqual(len(res), 1)  # GAS と同じく、エラーのところで止まる
        self.assertEqual(res[0].error, "行4: 重複警告: グラスの検品は使用履歴に存在しています。")

    def test_input_errors(self):
        self.assertEqual(run([s.plan_row("1-1")])[0].error,
                         "行4: 募集番号の先頭が空です(この会社で最初の予約行は必須入力です)")
        self.assertIn("画像カテゴリーが空です", run([s.plan_row("1-1", prefix="X1", image="")])[0].error)
        self.assertIn("会社「無い会社」が会社情報マスターに見つかりません",
                      run([s.plan_row("1-1", prefix="X1", company="無い会社")])[0].error)

    def test_old_format_is_not_made_but_numbers_continue(self):
        rows = [s.plan_row("1-1", count="2", prefix="CB1", fmt="旧FMT"), s.plan_row("2-1", count="1")]
        res = run(rows)
        self.assertIn("旧FMT", res[0].error)
        self.assertEqual(res[0].rows, [])
        self.assertEqual(res[1].rows[0]["募集番号"], "CB3")

    def test_done_rows_are_skipped_like_gas(self):
        rows = [s.plan_row("1-1", prefix="CB1", done="✅完了(2026-11-17 10:00) 3件")]
        self.assertEqual(g.read_targets(s.CONFIG_HEAD + rows), [])
        self.assertEqual(len(g.read_targets(s.CONFIG_HEAD + rows, include_done=True)), 1)

    def test_later_groups_avoid_titles_used_earlier_in_the_run(self):
        rows = [s.plan_row("1-1", count="3", prefix="CB1"), s.plan_row("2-1", count="3")]
        res = run(rows)
        first = {r["募集職種"].split("」")[0] for r in res[0].rows}
        second = {r["募集職種"].split("」")[0] for r in res[1].rows}
        self.assertEqual((first, second), ({"「半導体の製造A"}, {"「半導体の製造B"}))

    def test_usage_sheet_is_not_written(self):
        u = s.usage()
        bank = g.build_bank(s.grids())
        g.run(bank, u, g.read_targets(s.CONFIG_HEAD + [s.plan_row("1-1", prefix="CB1")]), now=NOW, today=NOW.date())
        self.assertTrue(u.title_rows)  # メモリ上だけ進める（シートに書く処理はない）

    def test_add_one_year_like_javascript(self):
        self.assertEqual(g.add_one_year(date(2028, 2, 29)), date(2029, 3, 1))


if __name__ == "__main__":
    unittest.main()
