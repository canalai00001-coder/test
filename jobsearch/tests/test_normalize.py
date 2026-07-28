import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest
from normalize import normalize_header, parse_yen, extract_labeled_text, load_mapping, normalize_row


class TestNormalizeHeader(unittest.TestCase):
    def test_full_width_vs_half_width_parens_match(self):
        self.assertEqual(normalize_header("TT （和彫り不可）"), normalize_header("TT(和彫り不可)"))

    def test_whitespace_variants_match(self):
        self.assertEqual(normalize_header("年齢  （上限）"), normalize_header("年齢（上限）"))


class TestParseYen(unittest.TestCase):
    def test_plain_yen_symbol(self):
        self.assertEqual(parse_yen("¥203,000"), 203000)

    def test_hourly_suffix(self):
        self.assertEqual(parse_yen("1,600円／時"), 1600)

    def test_man_yen(self):
        self.assertEqual(parse_yen("53万円"), 530000)

    def test_bare_number_with_padding(self):
        self.assertEqual(parse_yen("700,000  "), 700000)

    def test_empty(self):
        self.assertIsNone(parse_yen(""))
        self.assertIsNone(parse_yen(None))


class TestExtractLabeledText(unittest.TestCase):
    def test_splits_bracket_labels(self):
        text = "【必要資格】・未経験OK【契約期間】・3ヶ月更新【試用期間】・2週間(1500円／時)"
        result = extract_labeled_text(text)
        self.assertEqual(result["必要資格"], "・未経験OK")
        self.assertEqual(result["契約期間"], "・3ヶ月更新")
        self.assertEqual(result["試用期間"], "・2週間(1500円／時)")

    def test_no_labels_returns_empty(self):
        self.assertEqual(extract_labeled_text("特になし"), {})


class TestNormalizeRowAcrossCompanies(unittest.TestCase):
    def test_bn_maps_core_fields_and_splits_labeled_qualification(self):
        mapping = load_mapping("bn")
        row = {
            "都道府県名": "北海道", "求人No.": "1", "企業名": "サンプル",
            "形態": "派遣", "職種": "組立", "勤務地": "北海道どこか",
            "資格": "【必要資格】・未経験OK【契約期間】・3ヶ月更新",
            "時給/日給": "1500円／時", "紹介料": "30万円",
        }
        result = normalize_row(row, mapping)
        self.assertEqual(result["company"], "BN")
        self.assertEqual(result["job_title"], "組立")
        self.assertEqual(result["wage_yen"], 1500)
        self.assertEqual(result["referral_fee_yen"], 300000)
        self.assertEqual(result["extra"]["labeled"]["必要資格"], "・未経験OK")

    def test_wi_referral_fee_matched_by_month_regex(self):
        mapping = load_mapping("wi")
        row = {"求人番号": "1", "7月紹介料": "203000"}
        result = normalize_row(row, mapping)
        self.assertEqual(result["referral_fee_yen"], 203000)

        row2 = {"求人番号": "2", "8月紹介料": "195000"}
        result2 = normalize_row(row2, mapping)
        self.assertEqual(result2["referral_fee_yen"], 195000)

    def test_wt_wage_prefers_first_nonempty_of_hourly_or_monthly(self):
        mapping = load_mapping("wt")
        row = {"仕事No": "1", "時給": "1600", "月給": ""}
        result = normalize_row(row, mapping)
        self.assertEqual(result["wage_text"], "1600")

        row2 = {"仕事No": "2", "時給": "", "月給": "290000"}
        result2 = normalize_row(row2, mapping)
        self.assertEqual(result2["wage_text"], "290000")

    def test_unmapped_columns_land_in_extra(self):
        mapping = load_mapping("nk")
        row = {"お仕事No": "1", "キャッチコピー": "安定の官公庁案件"}
        result = normalize_row(row, mapping)
        self.assertEqual(result["extra"]["キャッチコピー"], "安定の官公庁案件")


if __name__ == "__main__":
    unittest.main()
