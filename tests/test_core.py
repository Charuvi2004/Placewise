"""Run: python -m pytest   (or: python tests/test_core.py)"""
import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import metrics as M, sample, store  # noqa: E402
from core.eligibility import check, rules_summary  # noqa: E402
from core.extract import FIELDS, extract, extract_with_rules, normalize, parse_date  # noqa: E402

T = date(2026, 11, 24)


def test_dates():
    assert parse_date("Apply by 30 Nov 2026", T) == date(2026, 11, 30)
    assert parse_date("Deadline: 05/12/2026", T) == date(2026, 12, 5)          # day first, Indian format
    assert parse_date("Last date: 3rd December", T) == date(2026, 12, 3)
    assert parse_date("Closes Jan 10", T) == date(2027, 1, 10)                # no year, already past → next year
    assert parse_date("Mayank 12", T) is None


def test_rule_extraction_accuracy_on_samples():
    total = wrong = 0
    for jd, truth in sample.sample_jds(T):
        got = extract_with_rules(jd, T)
        for k in ("min_cgpa", "branches", "max_backlogs", "batch", "deadline", "ctc_lpa"):   # the eligibility-critical fields
            assert sample.count_corrections({k: got[k]}, {k: truth[k]}) == 0, (truth["company"], k, got[k], truth[k])
        total += len(FIELDS)
        wrong += sample.count_corrections(got, truth)
    assert (total - wrong) / total >= 0.9


def test_specific_phrasings():
    assert extract_with_rules("Students with 6.5 CGPA and above. Maximum 1 active backlog allowed.", T)["min_cgpa"] == 6.5
    assert extract_with_rules("No CGPA criteria. Open to all branches.", T)["min_cgpa"] is None
    assert extract_with_rules("Eligible: CSE, IT and ECE", T)["branches"] == ["CSE", "IT", "ECE"]
    assert extract_with_rules("Eligible: it is open to Mechanical students", T)["branches"] == ["ME"]   # "it" isn't IT
    assert extract_with_rules("No active backlogs", T)["max_backlogs"] == 0
    assert extract_with_rules("Package: ₹ 4,50,000 per annum", T)["ctc_lpa"] == 4.5


def test_normalize_cleans_model_output():
    n = normalize({"min_cgpa": "75", "branches": ["CSE", "XYZ"], "deadline": "2026-12-01T00:00", "batch": "2027"})
    assert n["min_cgpa"] is None and n["branches"] == ["CSE"] and n["deadline"] == "2026-12-01" and n["batch"] == 2027


def test_extract_falls_back_when_gemini_fails():
    fields, method, note = extract("CGPA: 7.0\nDeadline: 30 Nov 2026", api_key="not-a-real-key", today=T)
    assert method == "rules" and fields["min_cgpa"] == 7.0 and note


def test_eligibility_reasons():
    d = {"min_cgpa": 7.5, "branches": ["CSE", "IT"], "max_backlogs": 0, "batch": 2027}
    ok, reasons = check({"cgpa": 7.49, "branch": "ECE", "active_backlogs": 1, "batch": 2026}, d)
    assert not ok and len(reasons) == 4
    assert check({"cgpa": 7.5, "branch": "IT", "active_backlogs": 0, "batch": 2027}, d) == (True, [])
    assert check({"cgpa": 5.0, "branch": "CE", "active_backlogs": 3, "batch": 2027},
                 {"min_cgpa": None, "branches": [], "max_backlogs": None, "batch": None})[0]
    assert rules_summary(d) == "CGPA ≥ 7.5 · CSE, IT · No backlogs · 2027 batch"


def test_store_seed_and_metrics():
    with tempfile.TemporaryDirectory() as tmp:
        conn = store.connect(str(Path(tmp) / "t.db"))
        sample.seed(conn, T)
        students, drives, apps = store.students(conn), store.drives(conn), store.applications(conn)
        assert len(students) == 150 and len(drives) == 6
        stats = M.drive_stats(students, drives, apps, T)
        assert set(stats.status) == {"open", "closed"}
        assert (stats.applied <= stats.eligible).all()
        ns, n = M.north_star(stats)
        assert 0.4 < ns < 0.9 and n > 0
        # nudge list = eligible minus anyone who responded
        d = next(x for x in drives if x["deadline"] >= T.isoformat())
        row = stats.set_index("id").loc[d["id"]]
        assert len(M.pending_students(students, d, apps)) == row.pending
        # a student applying moves out of the nudge list
        roll = M.pending_students(students, d, apps).roll_no.iloc[0]
        store.set_application(conn, d["id"], roll, "applied")
        assert roll not in set(M.pending_students(students, d, store.applications(conn)).roll_no)
        # upload validation
        try:
            store.replace_students(conn, pd.DataFrame({"roll_no": ["1"]}))
            raise AssertionError("should have failed")
        except ValueError:
            pass


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t(); print("ok ", t.__name__)
    print(f"{len(tests)} passed")
