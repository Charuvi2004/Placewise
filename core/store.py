"""SQLite storage. One file, no server: fine for a demo or a single placement cell."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import pandas as pd

STUDENT_COLUMNS = ["roll_no", "name", "branch", "cgpa", "active_backlogs", "batch"]
SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
  roll_no TEXT PRIMARY KEY, name TEXT, branch TEXT, cgpa REAL, active_backlogs INTEGER, batch INTEGER);
CREATE TABLE IF NOT EXISTS drives (
  id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, role TEXT, ctc_lpa REAL, min_cgpa REAL,
  branches TEXT, max_backlogs INTEGER, batch INTEGER, deadline TEXT, location TEXT, apply_link TEXT,
  jd_text TEXT, method TEXT, fields_corrected INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS applications (
  drive_id INTEGER, roll_no TEXT, status TEXT, ts TEXT, PRIMARY KEY (drive_id, roll_no));
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def is_empty(conn) -> bool:
    return conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 0


def replace_students(conn, df: pd.DataFrame) -> int:
    missing = [c for c in STUDENT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {', '.join(missing)}")
    d = df[STUDENT_COLUMNS].copy()
    d["roll_no"] = d.roll_no.astype(str).str.strip()
    d["branch"] = d.branch.astype(str).str.strip().str.upper()
    d["cgpa"] = pd.to_numeric(d.cgpa, errors="raise")
    d["active_backlogs"] = pd.to_numeric(d.active_backlogs, errors="raise").astype(int)
    d["batch"] = pd.to_numeric(d.batch, errors="raise").astype(int)
    with conn:
        conn.execute("DELETE FROM students")
        conn.executemany("INSERT INTO students VALUES (?,?,?,?,?,?)", d.itertuples(index=False, name=None))
    return len(d)


def students(conn) -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM students ORDER BY roll_no", conn)


def add_drive(conn, f: dict, jd_text: str, method: str, fields_corrected: int, created_at: str | None = None) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO drives (company, role, ctc_lpa, min_cgpa, branches, max_backlogs, batch, deadline, location,"
            " apply_link, jd_text, method, fields_corrected, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f["company"], f["role"], f["ctc_lpa"], f["min_cgpa"], json.dumps(f["branches"] or []), f["max_backlogs"],
             f["batch"], f["deadline"], f["location"], f["apply_link"], jd_text, method, fields_corrected,
             created_at or now_iso()))
    return cur.lastrowid


def drives(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM drives ORDER BY deadline, id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["branches"] = json.loads(d["branches"] or "[]")
        out.append(d)
    return out


def delete_drive(conn, drive_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM applications WHERE drive_id = ?", (drive_id,))
        conn.execute("DELETE FROM drives WHERE id = ?", (drive_id,))


def set_application(conn, drive_id: int, roll_no: str, status: str | None, ts: str | None = None) -> None:
    """status: 'applied', 'not_interested', or None to clear."""
    with conn:
        if status is None:
            conn.execute("DELETE FROM applications WHERE drive_id = ? AND roll_no = ?", (drive_id, roll_no))
        else:
            conn.execute("INSERT OR REPLACE INTO applications VALUES (?,?,?,?)", (drive_id, roll_no, status, ts or now_iso()))


def applications(conn) -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM applications", conn)


def reset(conn) -> None:
    with conn:
        for t in ("applications", "drives", "students"):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'drives'")
