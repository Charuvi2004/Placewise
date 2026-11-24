"""Coordinator metrics. North Star: share of eligible students who apply before the deadline."""
from __future__ import annotations

from datetime import date

import pandas as pd

from .eligibility import check

NORTH_STAR_TARGET = 0.80   # planning assumption; replace with baseline + 15 points once H1 is measured


def eligibility_matrix(students: pd.DataFrame, drives: list[dict]) -> pd.DataFrame:
    """One row per (drive, student) with eligible flag and reasons."""
    rows = []
    recs = students.to_dict("records")
    for d in drives:
        for s in recs:
            ok, reasons = check(s, d)
            rows.append({"drive_id": d["id"], "roll_no": s["roll_no"], "eligible": ok, "reasons": "; ".join(reasons)})
    return pd.DataFrame(rows, columns=["drive_id", "roll_no", "eligible", "reasons"])


def drive_stats(students: pd.DataFrame, drives: list[dict], apps: pd.DataFrame, today: date) -> pd.DataFrame:
    m = eligibility_matrix(students, drives)
    a = apps[apps.status == "applied"][["drive_id", "roll_no"]].assign(applied=True) if len(apps) else \
        pd.DataFrame(columns=["drive_id", "roll_no", "applied"])
    ni = apps[apps.status == "not_interested"][["drive_id", "roll_no"]].assign(declined=True) if len(apps) else \
        pd.DataFrame(columns=["drive_id", "roll_no", "declined"])
    m = m.merge(a, how="left", on=["drive_id", "roll_no"]).merge(ni, how="left", on=["drive_id", "roll_no"])
    m["applied"] = m.applied.eq(True)
    m["declined"] = m.declined.eq(True)
    rows = []
    for d in drives:
        x = m[(m.drive_id == d["id"]) & m.eligible]
        deadline = date.fromisoformat(d["deadline"]) if d.get("deadline") else None
        status = "closed" if deadline and deadline < today else "open"
        eligible, applied = len(x), int(x.applied.sum())
        rows.append({
            "id": d["id"], "company": d["company"], "role": d["role"], "deadline": deadline, "status": status,
            "days_left": (deadline - today).days if deadline else None,
            "eligible": eligible, "applied": applied, "not_interested": int(x.declined.sum()),
            "pending": int((~x.applied & ~x.declined).sum()),
            "rate": applied / eligible if eligible else None,
            "fields_corrected": d.get("fields_corrected"), "method": d.get("method"),
        })
    return pd.DataFrame(rows)


def north_star(stats: pd.DataFrame) -> tuple[float | None, int]:
    """Eligible application rate across CLOSED drives (their result is final)."""
    c = stats[stats.status == "closed"]
    elig = c.eligible.sum()
    return (c.applied.sum() / elig if elig else None), int(elig)


def pending_students(students: pd.DataFrame, drive: dict, apps: pd.DataFrame) -> pd.DataFrame:
    """Eligible students who have neither applied nor declined: the nudge list."""
    acted = set(apps[apps.drive_id == drive["id"]].roll_no) if len(apps) else set()
    rows = [s for s in students.to_dict("records") if check(s, drive)[0] and s["roll_no"] not in acted]
    return pd.DataFrame(rows, columns=students.columns)


def silent_students(students: pd.DataFrame, drives: list[dict], apps: pd.DataFrame, today: date) -> pd.DataFrame:
    """Students eligible for at least one open drive who haven't applied to any open drive."""
    open_d = [d for d in drives if d.get("deadline") and date.fromisoformat(d["deadline"]) >= today]
    applied = set(apps[(apps.status == "applied") & apps.drive_id.isin([d["id"] for d in open_d])].roll_no) if len(apps) else set()
    rows = []
    for s in students.to_dict("records"):
        n = sum(check(s, d)[0] for d in open_d)
        if n and s["roll_no"] not in applied:
            rows.append({**s, "eligible_open_drives": n})
    return pd.DataFrame(rows, columns=[*students.columns, "eligible_open_drives"])
