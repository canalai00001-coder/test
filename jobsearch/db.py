import json
import sqlite3
from pathlib import Path

from normalize import COMMON_FIELDS

DB_PATH = Path(__file__).parent / "jobs.db"

_COLUMNS_SQL = ",\n    ".join(f'"{f}" TEXT' for f in COMMON_FIELDS if f not in ("wage_yen", "monthly_income_yen", "referral_fee_yen"))


def get_connection(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {_COLUMNS_SQL},
            wage_yen INTEGER,
            monthly_income_yen INTEGER,
            referral_fee_yen INTEGER,
            extra TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_prefecture ON jobs(prefecture)")
    conn.commit()


def clear_company(conn, company):
    conn.execute("DELETE FROM jobs WHERE company = ?", (company,))
    conn.commit()


def insert_jobs(conn, jobs):
    if not jobs:
        return
    fields = [f for f in COMMON_FIELDS if f not in ("wage_yen", "monthly_income_yen", "referral_fee_yen")]
    fields += ["wage_yen", "monthly_income_yen", "referral_fee_yen", "extra"]
    placeholders = ", ".join("?" for _ in fields)
    columns = ", ".join(f'"{f}"' for f in fields)
    rows = []
    for job in jobs:
        row = [job.get(f) for f in fields[:-1]]
        row.append(json.dumps(job.get("extra") or {}, ensure_ascii=False))
        rows.append(row)
    conn.executemany(f"INSERT INTO jobs ({columns}) VALUES ({placeholders})", rows)
    conn.commit()


def search_jobs(conn, q=None, company=None, prefecture=None, employment_type=None, limit=50, offset=0):
    clauses = []
    params = []
    if q:
        clauses.append("(job_title LIKE ? OR job_detail LIKE ? OR workplace LIKE ? OR remarks LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like, like]
    if company:
        clauses.append("company = ?")
        params.append(company)
    if prefecture:
        clauses.append("prefecture LIKE ?")
        params.append(f"%{prefecture}%")
    if employment_type:
        clauses.append("employment_type = ?")
        params.append(employment_type)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(f"SELECT COUNT(*) FROM jobs {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM jobs {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    return total, [dict(r) for r in rows]


def facets(conn):
    companies = [r[0] for r in conn.execute("SELECT DISTINCT company FROM jobs ORDER BY company")]
    prefectures = [r[0] for r in conn.execute("SELECT DISTINCT prefecture FROM jobs WHERE prefecture IS NOT NULL ORDER BY prefecture")]
    employment_types = [r[0] for r in conn.execute("SELECT DISTINCT employment_type FROM jobs WHERE employment_type IS NOT NULL ORDER BY employment_type")]
    return {"companies": companies, "prefectures": prefectures, "employment_types": employment_types}
