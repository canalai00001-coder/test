"""Read each company's raw CSV export, normalize it, and load it into jobs.db.

Usage:
    python3 ingest.py                  # uses sample_data/ (dummy demo data)
    python3 ingest.py --data-dir real_data
"""
import argparse
import csv
from pathlib import Path

from db import get_connection, init_db, clear_company, insert_jobs
from normalize import load_mapping, normalize_row

MAPPING_TO_CSV = {
    "bn": "bn.csv",
    "hr_provision": "hr_provision.csv",
    "nk": "nk.csv",
    "wi": "wi.csv",
    "wt": "wt.csv",
    "hirayama": "hirayama.csv",
}


def ingest_company(conn, mapping_key: str, csv_path: Path):
    if not csv_path.exists():
        print(f"  skip {mapping_key}: {csv_path} not found")
        return 0
    mapping = load_mapping(mapping_key)
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [normalize_row(row, mapping) for row in reader]
    clear_company(conn, mapping["company"])
    insert_jobs(conn, rows)
    print(f"  {mapping['company']}: {len(rows)} 件 取り込み")
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="sample_data")
    args = parser.parse_args()

    data_dir = Path(__file__).parent / args.data_dir
    conn = get_connection()
    init_db(conn)

    total = 0
    print(f"取り込み元: {data_dir}")
    for mapping_key, csv_name in MAPPING_TO_CSV.items():
        total += ingest_company(conn, mapping_key, data_dir / csv_name)
    print(f"合計 {total} 件")


if __name__ == "__main__":
    main()
