"""Who can apply to a drive, and why not."""
from __future__ import annotations


def check(student: dict, drive: dict) -> tuple[bool, list[str]]:
    """Returns (eligible, reasons). Reasons are plain sentences a student can act on."""
    reasons = []
    cgpa = round(float(student["cgpa"]), 2)
    if drive.get("min_cgpa") is not None and cgpa < float(drive["min_cgpa"]):
        reasons.append(f"CGPA {cgpa:.2f} is below the {float(drive['min_cgpa']):g} cut-off")
    if drive.get("branches") and student["branch"] not in drive["branches"]:
        reasons.append(f"{student['branch']} isn't an eligible branch (open to {', '.join(drive['branches'])})")
    if drive.get("max_backlogs") is not None and int(student["active_backlogs"]) > int(drive["max_backlogs"]):
        allowed = "no backlogs" if int(drive["max_backlogs"]) == 0 else f"at most {drive['max_backlogs']}"
        reasons.append(f"{int(student['active_backlogs'])} active backlog(s); this drive allows {allowed}")
    if drive.get("batch") and int(student["batch"]) != int(drive["batch"]):
        reasons.append(f"Batch {student['batch']}; this drive is for {drive['batch']}")
    return (not reasons, reasons)


def rules_summary(drive: dict) -> str:
    parts = [f"CGPA ≥ {drive['min_cgpa']:g}" if drive.get("min_cgpa") is not None else "No CGPA cut-off",
             ", ".join(drive["branches"]) if drive.get("branches") else "All branches"]
    if drive.get("max_backlogs") is not None:
        parts.append("No backlogs" if drive["max_backlogs"] == 0 else f"≤ {drive['max_backlogs']} backlogs")
    if drive.get("batch"):
        parts.append(f"{drive['batch']} batch")
    return " · ".join(parts)
