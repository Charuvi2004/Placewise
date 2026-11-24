"""Demo data: fictional companies and fake students. Deadlines are set relative to
'today' so the demo always has open and closed drives. Each sample JD has a
hand-checked TRUTH, used both to seed drives and to measure extraction accuracy."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

from . import store
from .eligibility import check
from .extract import FIELDS, extract_with_rules


def _fmt(d: date, style: str) -> str:
    return {"dmy": d.strftime("%d %b %Y"), "slash": d.strftime("%d/%m/%Y"),
            "noyear": f"{d.day}{'th' if 10 <= d.day % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d.day % 10, 'th')} {d.strftime('%B')}",
            "long": d.strftime("%B %-d, %Y")}[style]


# (offset days from today, date style, JD template, truth without deadline)
SAMPLES = [
    (6, "dmy", """Company: Nimbus Analytics Pvt Ltd
Role: Software Development Engineer 1
Location: Bengaluru
CTC: 12 LPA
Eligibility: B.Tech CSE / IT, 2027 batch
Minimum CGPA: 7.5 (no active backlogs)
Apply by: {D}
Registration link: https://forms.gle/example-nimbus""",
     dict(company="Nimbus Analytics Pvt Ltd", role="Software Development Engineer 1", ctc_lpa=12.0, min_cgpa=7.5,
          branches=["CSE", "IT"], max_backlogs=0, batch=2027, location="Bengaluru", apply_link="https://forms.gle/example-nimbus")),
    (9, "noyear", """Kestrel Fintech is hiring Graduate Engineer Trainees for its Pune office!
Position: Graduate Engineer Trainee
Open to all branches of B.E./B.Tech graduating in 2027.
Students with 6.5 CGPA and above may apply. Maximum 1 active backlog allowed.
Package: CTC of ₹ 6,50,000 per annum
Last date to register: {D}""",
     dict(company="Kestrel Fintech", role="Graduate Engineer Trainee", ctc_lpa=6.5, min_cgpa=6.5, branches=[],
          max_backlogs=1, batch=2027, location="Pune", apply_link=None)),
    (3, "slash", """TARANG SYSTEMS – Campus Drive 2026-27
Designation: Hardware Design Engineer
Eligible branches: Electronics and Communication, Electrical and Electronics
CGPA cut-off: 7.0
No standing backlogs.
Compensation: 9 LPA + joining bonus
Job Location: Hyderabad
Deadline: {D}""",
     dict(company="Tarang Systems", role="Hardware Design Engineer", ctc_lpa=9.0, min_cgpa=7.0, branches=["ECE", "EEE"],
          max_backlogs=0, batch=None, location="Hyderabad", apply_link=None)),
    (15, "long", """Quillbyte Labs
Role: Product Engineering Intern (6 months, PPO-based)
Branches: CSE, IT, ECE
Minimum 8.0 CGPA, no backlogs
CTC on conversion: 18 LPA
Graduation year: 2027
Apply before {D}: https://quillbyte.example/careers/campus""",
     dict(company="Quillbyte Labs", role="Product Engineering Intern (6 months, PPO-based)", ctc_lpa=18.0, min_cgpa=8.0,
          branches=["CSE", "IT", "ECE"], max_backlogs=0, batch=2027, location=None,
          apply_link="https://quillbyte.example/careers/campus")),
    (-4, "dmy", """Organisation: Banyan Retail Tech
Profile: Business Analyst
Stream: Any branch
CGPA: 6.0 and above
Package: 7.5 LPA
Location: Mumbai
Deadline: {D}""",
     dict(company="Banyan Retail Tech", role="Business Analyst", ctc_lpa=7.5, min_cgpa=6.0, branches=[],
          max_backlogs=None, batch=None, location="Mumbai", apply_link=None)),
    (-9, "dmy", """Orbit Mechanica Pvt Ltd
Role: Graduate Trainee – Manufacturing
Eligible: Mechanical and Civil Engineering students, batch of 2027
CGPA 6.5+, up to 2 backlogs
CTC: 5.5 LPA
Work location: Chennai
Last date: {D}""",
     dict(company="Orbit Mechanica Pvt Ltd", role="Graduate Trainee – Manufacturing", ctc_lpa=5.5, min_cgpa=6.5,
          branches=["ME", "CE"], max_backlogs=2, batch=2027, location="Chennai", apply_link=None)),
]


def sample_jds(today: date) -> list[tuple[str, dict]]:
    """[(jd_text, truth)] with deadlines filled in relative to today."""
    out = []
    for offset, style, tmpl, truth in SAMPLES:
        d = today + timedelta(days=offset)
        out.append((tmpl.replace("{D}", _fmt(d, style)), {**truth, "deadline": d.isoformat()}))
    return out


def fake_students(n: int = 150, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    first = ["Aarav", "Vivaan", "Aditya", "Ishaan", "Rohan", "Arjun", "Kabir", "Siddharth", "Karthik", "Rahul",
             "Ananya", "Diya", "Saanvi", "Ishita", "Meera", "Priya", "Sneha", "Kavya", "Riya", "Nandini",
             "Harsh", "Yash", "Tanvi", "Pooja", "Neha", "Varun", "Aman", "Shreya", "Deepak", "Lakshmi"]
    last = ["Sharma", "Verma", "Iyer", "Nair", "Reddy", "Patel", "Gupta", "Singh", "Das", "Menon",
            "Rao", "Kulkarni", "Joshi", "Mehta", "Chopra", "Banerjee", "Pillai", "Mishra", "Yadav", "Shetty"]
    branches = rng.choice(["CSE", "IT", "ECE", "EEE", "ME", "CE"], size=n, p=[0.27, 0.17, 0.2, 0.13, 0.13, 0.1])
    return pd.DataFrame({
        "roll_no": [f"21{b}{i:03d}" for i, b in enumerate(branches, start=1)],
        "name": [f"{rng.choice(first)} {rng.choice(last)}" for _ in range(n)],
        "branch": branches,
        "cgpa": np.clip(rng.normal(7.4, 0.9, n), 5.5, 9.8).round(2),
        "active_backlogs": rng.choice([0, 1, 2, 3], size=n, p=[0.8, 0.12, 0.06, 0.02]),
        "batch": 2027,
    })


def count_corrections(extracted: dict, final: dict) -> int:
    def same(a, b):
        if isinstance(a, list) or isinstance(b, list):
            return sorted(a or []) == sorted(b or [])
        if isinstance(a, float) or isinstance(b, float):
            return a is not None and b is not None and abs(float(a) - float(b)) < 1e-6 or (a is None and b is None)
        return (a or None) == (b or None)
    return sum(not same(extracted.get(k), final.get(k)) for k in FIELDS)


def seed(conn, today: date, seed_value: int = 11) -> None:
    """Fill an empty database with fake students, the sample drives and simulated responses."""
    rng = np.random.default_rng(seed_value)
    students = fake_students()
    store.replace_students(conn, students)
    recs = students.to_dict("records")
    for jd, truth in sample_jds(today):
        extracted = extract_with_rules(jd, today)
        deadline = date.fromisoformat(truth["deadline"])
        created = datetime.combine(deadline - timedelta(days=8), time(10, 0))
        drive_id = store.add_drive(conn, truth, jd, "rules", count_corrections(extracted, truth), created.isoformat())
        drive = {**truth, "id": drive_id}
        closed = deadline < today
        span_end = datetime.combine(min(deadline, today), time(18, 0))
        for s in recs:
            if not check(s, drive)[0]:
                continue
            r = rng.random()
            p_apply = 0.64 if closed else 0.38
            status = "applied" if r < p_apply else ("not_interested" if r < p_apply + 0.08 else None)
            if status:
                ts = created + (span_end - created) * float(rng.random())
                store.set_application(conn, drive_id, s["roll_no"], status, ts.isoformat(timespec="seconds"))
