# Placewise: AI placement-cell tracker

A Streamlit app for college placement cells. Paste a job description, and AI (Gemini, or a built-in rule-based parser) drafts the eligibility rules: CGPA cut-off, branches, backlogs, batch, deadline and CTC. A coordinator checks and publishes. Every student then sees only the drives they qualify for, with the reason for any they don't, and coordinators see exactly who still needs a nudge.

> **Demo data:** six fictional companies and 150 fake students, with deadlines set relative to today, so there are always open and closed drives. No real company or student data is included.

## What to try

| View | What it shows |
| --- | --- |
| **Student** | Pick a student. You see eligible open drives sorted by deadline, warnings for anything closing within 2 days, *Mark as applied* / *Not interested*, and every ineligible drive with the reason ("CGPA 7.12 is below the 7.5 cut-off") |
| **Coordinator: add a drive** | Load an example JD and click *Extract rules*. Check the fields next to the JD; the live count shows how many students these rules make eligible. Publishing records how many fields you had to correct |
| **Coordinator: dashboard** | North Star (eligible application rate on closed drives), application rate per drive, AI fields corrected per JD, and a **nudge list** of eligible students who haven't responded, with a ready-made WhatsApp reminder and CSV download |
| **Data & settings** | Upload a real student list (CSV), export everything, reset the demo |

## Run it

**On the web (no install):** push this folder to a public GitHub repo, then on share.streamlit.io choose *Create app* → your repo → `app.py`. To use Gemini, open **App settings → Secrets** and add:

```toml
GEMINI_API_KEY = "your key"          # free key from Google AI Studio
# GEMINI_MODEL = "gemini-3.8-flash"  # optional
```

Without a key, the rule-based parser runs instead, and everything still works.

**Locally:** `pip install -r requirements.txt`, then `streamlit run app.py`.

**Tests:** `python -m pytest` (or `python tests/test_core.py`).

## How it works

| File | Role |
| --- | --- |
| `core/extract.py` | JD → rules. Gemini structured output with a JSON schema, a regex fallback, and one `normalize()` step both share. If Gemini fails, it falls back automatically |
| `core/eligibility.py` | `check(student, drive)` → eligible or not, plus plain-language reasons |
| `core/metrics.py` | Per-drive stats, North Star, nudge list, "eligible but silent" students |
| `core/store.py` | SQLite: students, drives, applications |
| `core/sample.py` | Fictional JDs with hand-checked correct answers, fake students, seeding |
| `app.py` | The Streamlit UI |

**Extraction accuracy:** on the six sample JDs, the rule-based parser gets 57 of 60 fields right (95%), and every eligibility-critical field (CGPA, branches, backlogs, batch, deadline, CTC) right. The misses are company names and a location written as prose; that's what the coordinator check is for. The tests enforce this.

**Why a human approves every drive:** a wrongly excluded student loses a real job opportunity. AI drafts, the coordinator decides, and the dashboard tracks how many fields needed fixing.

## Student data

`data/students_template.csv` shows the format: `roll_no, name, branch, cgpa, active_backlogs, batch`, with branch codes `CSE, IT, ECE, EEE, ME, CE`. Collect only these fields, with the placement officer's approval and students' consent. **Never upload real student data to a public demo link**; run a private deployment for a real pilot.

## Limitations

- No logins: the student view uses a picker. A real rollout needs college SSO or email sign-in.
- On Streamlit Community Cloud, the SQLite file resets when the app restarts. Fine for a demo; a real pilot needs a hosted database (e.g. Supabase or Google Sheets).
- The rule-based parser handles common JD phrasings, not every one; use Gemini for messy emails.
