"""Normalize raw per-company job spreadsheets into the common schema.

Each alliance company sends job listings in its own spreadsheet layout.
A mapping file (mapping/*.json) describes, per company, which source
column feeds which common-schema field. This module applies that mapping
and does light value cleanup (yen amounts, "labeled text" blocks like
"【契約期間】...【試用期間】...").
"""
import json
import re
import unicodedata
from pathlib import Path

MAPPING_DIR = Path(__file__).parent / "mapping"

COMMON_FIELDS = [
    "company", "job_no", "employment_type", "job_title", "job_detail",
    "prefecture", "workplace", "workplace_address", "nearest_station",
    "wage_type", "wage_text", "wage_yen", "monthly_income_text", "monthly_income_yen",
    "referral_fee_text", "referral_fee_yen", "gender", "age_text",
    "age_min_text", "age_max_text", "holiday", "shift", "work_hours_text",
    "dorm_available", "dorm_fee_text", "commute_fee_text", "commute_method",
    "foreign_ok", "tattoo_ok", "interview_deadline", "start_date", "remarks",
]


def normalize_header(name: str) -> str:
    """Collapse whitespace/width variants so header names compare equal
    across companies (e.g. "TT （和彫り不可）" vs "TT(和彫り不可)")."""
    if name is None:
        return ""
    n = unicodedata.normalize("NFKC", name)  # full-width -> half-width
    n = re.sub(r"\s+", "", n)  # drop all whitespace (incl. full-width space)
    return n


_YEN_MAN = re.compile(r"([\d,]+(?:\.\d+)?)\s*万円")
_YEN_PLAIN = re.compile(r"[¥\\]?\s*([\d,]+)\s*円?")


def parse_yen(text) -> int | None:
    """Best-effort extraction of a yen amount from free-form text.
    Handles "¥203,000", "1,600円／時", "53万円", "700,000  "."""
    if not text:
        return None
    text = unicodedata.normalize("NFKC", str(text)).strip()
    if not text:
        return None
    m = _YEN_MAN.search(text)
    if m:
        return int(round(float(m.group(1).replace(",", "")) * 10000))
    m = _YEN_PLAIN.search(text)
    if m:
        digits = m.group(1).replace(",", "")
        if digits.isdigit():
            return int(digits)
    return None


_LABEL_BLOCK = re.compile(r"【([^】]+)】\s*([^【]*)")


def extract_labeled_text(text: str) -> dict:
    """Split a bundled cell like "【必要資格】...【契約期間】..." into a
    dict keyed by label. Returns {} if the text has no 【】 markers."""
    if not text:
        return {}
    result = {}
    for label, body in _LABEL_BLOCK.findall(text):
        result[label.strip()] = body.strip()
    return result


def load_mapping(company_key: str) -> dict:
    path = MAPPING_DIR / f"{company_key}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _first_nonempty(row_norm: dict, source_names, default=None):
    if isinstance(source_names, str):
        source_names = [source_names]
    for name in source_names:
        key = normalize_header(name)
        val = row_norm.get(key)
        if val is not None and str(val).strip() != "":
            return str(val).strip()
    return default


def normalize_row(row: dict, mapping: dict) -> dict:
    """Apply one company's mapping to one raw CSV row (dict keyed by the
    original header names) and return a common-schema dict."""
    row_norm = {normalize_header(k): v for k, v in row.items()}

    result = {f: None for f in COMMON_FIELDS}
    result["company"] = mapping["company"]

    field_map = mapping.get("field_map", {})
    for target_field, source in field_map.items():
        result[target_field] = _first_nonempty(row_norm, source)

    for pattern, target_field in mapping.get("regex_field_map", []):
        if result.get(target_field):
            continue
        rx = re.compile(pattern)
        for header, value in row.items():
            if value and str(value).strip() and rx.match(normalize_header(header)):
                result[target_field] = str(value).strip()
                break

    if result.get("wage_text"):
        result["wage_yen"] = parse_yen(result["wage_text"])
    if result.get("monthly_income_text"):
        result["monthly_income_yen"] = parse_yen(result["monthly_income_text"])
    if result.get("referral_fee_text"):
        result["referral_fee_yen"] = parse_yen(result["referral_fee_text"])

    extra = {}
    labeled_fields_norm = {normalize_header(h) for h in mapping.get("labeled_text_fields", [])}
    mapped_source_headers = set()
    for source in field_map.values():
        for s in (source if isinstance(source, list) else [source]):
            mapped_source_headers.add(normalize_header(s))

    for header, value in row.items():
        norm_header = normalize_header(header)
        if norm_header in labeled_fields_norm:
            if value:
                labeled = extract_labeled_text(str(value))
                if labeled:
                    extra.setdefault("labeled", {}).update(labeled)
                elif str(value).strip():
                    extra[header] = value
            continue
        if norm_header in mapped_source_headers:
            continue
        if value is not None and str(value).strip() != "":
            extra[header] = value

    result["extra"] = extra
    return result
