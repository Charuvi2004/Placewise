"""Turn job-description text into structured eligibility rules.

Two extractors return the same dict shape:
  * extract_with_gemini(): Gemini structured output (needs GEMINI_API_KEY)
  * extract_with_rules():  regex fallback, works offline
Both go through normalize(), so the rest of the app never cares which one ran.
A coordinator reviews every field before a drive is published.
"""
from __future__ import annotations

import json
import re
from datetime import date

BRANCHES = ["CSE", "IT", "ECE", "EEE", "ME", "CE"]
BRANCH_NAMES = {
    "CSE": "Computer Science", "IT": "Information Technology", "ECE": "Electronics & Communication",
    "EEE": "Electrical & Electronics", "ME": "Mechanical", "CE": "Civil",
}
FIELDS = ["company", "role", "ctc_lpa", "min_cgpa", "branches", "max_backlogs", "batch", "deadline",
          "location", "apply_link"]

_MONTH_LIST = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
               "october", "november", "december"]
MONTHS = {}
for _i, _m in enumerate(_MONTH_LIST, start=1):
    MONTHS[_m] = MONTHS[_m[:3]] = _i
MONTHS["sept"] = 9


def _month(word: str) -> int | None:
    return MONTHS.get(word.lower().rstrip("."))


# ------------------------------------------------------------------ dates
def parse_date(text: str, today: date | None = None) -> date | None:
    """First date in text: 30 Nov 2026, 30th November, 30/11/2026 (day first), 2026-11-30, November 30, 2026.
    A date written without a year is taken as the next such date from today."""
    today = today or date.today()
    pats = [
        (r"(\d{4})-(\d{1,2})-(\d{1,2})", lambda m: (int(m[1]), int(m[2]), int(m[3]))),
        (r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", lambda m: (int(m[3]), int(m[2]), int(m[1]))),
        (r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s*(\d{4})?",
         lambda m: (int(m[3]) if m[3] else None, _month(m[2]), int(m[1]))),
        (r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?",
         lambda m: (int(m[3]) if m[3] else None, _month(m[1]), int(m[2]))),
    ]
    for pat, conv in pats:
        for m in re.finditer(pat, text):
            y, mo, d = conv(m)
            if not mo:
                continue
            year_given = y is not None
            y = y or today.year
            try:
                dt = date(y, mo, d)
            except ValueError:
                continue
            if not year_given and dt < today:
                dt = date(y + 1, mo, d)
            return dt
    return None


# ------------------------------------------------------------------ rule-based
def _field(text: str, labels: str) -> str | None:
    m = re.search(rf"(?im)^\s*(?:{labels})\s*[:\-–]\s*(.+?)\s*$", text)
    return m.group(1).strip() if m else None


def _branches(text: str) -> list[str]:
    scope = "\n".join(l for l in text.splitlines()
                      if re.search(r"(?i)branch|stream|discipline|eligib|degree|b\.?\s?tech|b\.?e\b", l)) or text
    if re.search(r"(?i)\b(all|any)\s+(branch(es)?|streams?|disciplines?)\b|open to all", scope):
        return []
    found = set()
    low = scope.lower()
    for code, words in {
        "CSE": ["computer science", "computer engineering"], "IT": ["information technology"],
        "ECE": ["electronics and communication", "electronics & communication", "electronics and telecommunication"],
        "EEE": ["electrical and electronics", "electrical & electronics", "electrical engineering"],
        "ME": ["mechanical"], "CE": ["civil"],
    }.items():
        if any(w in low for w in words):
            found.add(code)
    for code in re.findall(r"\b(CSE|CS|IT|ECE|EEE|EE|ME|CE)\b", scope):   # upper-case codes only ("it" is a word)
        found.add({"CS": "CSE", "EE": "EEE"}.get(code, code))
    return [b for b in BRANCHES if b in found]


def extract_with_rules(text: str, today: date | None = None) -> dict:
    today = today or date.today()
    out: dict = {k: None for k in FIELDS}
    first_line = next((l.strip() for l in text.splitlines() if l.strip()), "")
    out["company"] = _field(text, "company|company name|organi[sz]ation|employer") or first_line[:80] or None
    out["role"] = _field(text, "role|position|designation|job title|job role|profile")
    out["location"] = _field(text, "location|job location|work location|place of posting")

    m = re.search(r"(?i)(?:ctc|package|compensation|salary|stipend)[^\n]*?(\d+(?:\.\d+)?)\s*(?:lpa|l\.p\.a|lakhs?|lacs?)", text)
    if m:
        out["ctc_lpa"] = float(m.group(1))
    else:
        m = re.search(r"(?i)(?:ctc|package|compensation|salary)[^\n]*?(?:₹|rs\.?|inr)\s*([\d,]{6,})", text)
        if m:
            out["ctc_lpa"] = round(int(m.group(1).replace(",", "")) / 1e5, 2)

    if not re.search(r"(?i)no\s+(?:minimum\s+)?(?:cgpa|cpi|gpa)\s+(?:criteria|cut-?off|requirement)", text):
        # "6.5 CGPA" first, then "CGPA: 7.5", so "CGPA and above ... 1 backlog" can't grab the wrong number
        for pat in [r"(?i)(?<![\d.])(\d(?:\.\d{1,2})?)[ \t]*(?:\+|and above|or above)?[ \t]*(?:cgpa|cpi|gpa)",
                    r"(?i)(?:cgpa|cpi|gpa)[^\n\d]{0,25}(\d{1,2}(?:\.\d{1,2})?)(?![\d])"]:
            m = re.search(pat, text)
            if m and 0 < float(m.group(1)) <= 10:
                out["min_cgpa"] = float(m.group(1))
                break

    out["branches"] = _branches(text)

    if re.search(r"(?i)\b(no|zero|nil)\s+(?:active\s+|live\s+|standing\s+)?backlogs?", text):
        out["max_backlogs"] = 0
    else:
        m = re.search(r"(?i)(?:max(?:imum)?|up\s*to|not\s+more\s+than)\s*(\d)\s*(?:active\s+)?backlogs?", text) \
            or re.search(r"(?i)(\d)\s*(?:active\s+)?backlogs?\s+(?:allowed|permitted)", text)
        if m:
            out["max_backlogs"] = int(m.group(1))

    m = re.search(r"(?i)(?:batch|graduating|passing\s*out|class\s+of|year\s+of\s+passing|graduation\s+year)[^\n\d]{0,25}(20\d{2})", text) \
        or re.search(r"(?i)\b(20\d{2})\s*(?:batch|pass-?outs?|graduates)", text)
    if m:
        out["batch"] = int(m.group(1))

    for line in text.splitlines():
        if re.search(r"(?i)deadline|last\s+date|apply\s+by|register\s+by|closes|before", line):
            d = parse_date(line, today)
            if d:
                out["deadline"] = d.isoformat()
                break

    m = re.search(r"https?://\S+", text)
    if m:
        out["apply_link"] = m.group(0).rstrip(").,")
    return normalize(out)


# ------------------------------------------------------------------ Gemini
SCHEMA = {
    "type": "object",
    "properties": {
        "company": {"type": ["string", "null"], "description": "Hiring company name"},
        "role": {"type": ["string", "null"], "description": "Job title / role"},
        "ctc_lpa": {"type": ["number", "null"], "description": "Annual CTC in lakhs per annum (LPA). Convert rupees to lakhs."},
        "min_cgpa": {"type": ["number", "null"], "description": "Minimum CGPA on a 10-point scale. null if none is stated."},
        "branches": {"type": "array", "items": {"type": "string", "enum": BRANCHES},
                     "description": "Eligible branches as codes. Empty list if all branches are eligible."},
        "max_backlogs": {"type": ["integer", "null"], "description": "Maximum active backlogs allowed. 0 for 'no backlogs'. null if not stated."},
        "batch": {"type": ["integer", "null"], "description": "Graduating year, e.g. 2027"},
        "deadline": {"type": ["string", "null"], "description": "Application deadline as YYYY-MM-DD"},
        "location": {"type": ["string", "null"]},
        "apply_link": {"type": ["string", "null"]},
    },
    "required": FIELDS,
}

PROMPT = """You extract eligibility rules from a campus placement job description for an Indian engineering college.
Branch codes: CSE = Computer Science, IT = Information Technology, ECE = Electronics & Communication,
EEE = Electrical & Electronics, ME = Mechanical, CE = Civil.
Rules: use null when a value is not stated; never guess. "All branches" means an empty list.
Dates are usually day/month/year. Today is {today}; a date without a year is the next such date.

Job description:
\"\"\"{jd}\"\"\""""


def extract_with_gemini(text: str, api_key: str, model: str = "gemini-3.8-flash", today: date | None = None) -> dict:
    from google import genai   # imported here so the app runs without the package

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=model,
        contents=PROMPT.format(today=(today or date.today()).isoformat(), jd=text[:12000]),
        config={"response_mime_type": "application/json", "response_json_schema": SCHEMA, "temperature": 0},
    )
    return normalize(json.loads(resp.text))


def extract(text: str, api_key: str | None = None, model: str | None = None, today: date | None = None) -> tuple[dict, str, str]:
    """Returns (fields, method, note). Falls back to rules if Gemini is unavailable or fails."""
    if api_key:
        try:
            return extract_with_gemini(text, api_key, model or "gemini-3.8-flash", today), "gemini", ""
        except Exception as e:   # bad key, quota, network, package missing
            return extract_with_rules(text, today), "rules", f"Gemini failed ({type(e).__name__}); used the rule-based parser."
    return extract_with_rules(text, today), "rules", ""


# ------------------------------------------------------------------ cleanup
def normalize(d: dict) -> dict:
    out = {k: d.get(k) for k in FIELDS}
    for k in ("company", "role", "location", "apply_link"):
        out[k] = (str(out[k]).strip() or None) if out[k] else None
    for k in ("ctc_lpa", "min_cgpa"):
        try:
            out[k] = float(out[k]) if out[k] not in (None, "") else None
        except (TypeError, ValueError):
            out[k] = None
    if out["min_cgpa"] is not None and not 0 < out["min_cgpa"] <= 10:
        out["min_cgpa"] = None
    for k in ("max_backlogs", "batch"):
        try:
            out[k] = int(out[k]) if out[k] not in (None, "") else None
        except (TypeError, ValueError):
            out[k] = None
    out["branches"] = [b for b in BRANCHES if b in set(out.get("branches") or [])]
    if out["deadline"]:
        try:
            out["deadline"] = date.fromisoformat(str(out["deadline"])[:10]).isoformat()
        except ValueError:
            out["deadline"] = None
    return out
