"""Placewise: AI placement-cell tracker.

    streamlit run app.py
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import metrics as M, sample, store
from core.eligibility import check, rules_summary
from core.extract import BRANCH_NAMES, BRANCHES, extract

HERE = Path(__file__).parent
DB_PATH = os.environ.get("PLACEWISE_DB", str(HERE / "data" / "placewise.db"))
# Dark analytics palette (dark-mode steps of the reference chart palette)
BLUE, INK, INK2, GRID, AXIS, MUTED = "#3987e5", "#f0efec", "#c3c2b7", "#2c2c2a", "#383835", "#898781"

st.set_page_config(page_title="Placewise · placement tracker", layout="wide")
st.markdown("""<style>
[data-testid="stMetric"] { background: #1a1a19; border: 1px solid #2c2c2a; border-radius: 12px; padding: 14px 16px; }
[data-testid="stMetricLabel"] p { color: #c3c2b7; font-size: 0.85rem; }
[data-testid="stMetricValue"] { font-weight: 700; letter-spacing: -0.01em; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color: #2c2c2a !important; background: #141413; border-radius: 12px; }
[data-testid="stSidebar"] { background: #121211; border-right: 1px solid #2c2c2a; }
[data-testid="stDataFrame"] { border: 1px solid #2c2c2a; border-radius: 10px; }
h1, h2, h3 { letter-spacing: -0.01em; }
</style>""", unsafe_allow_html=True)


def secret(name: str) -> str | None:
    try:
        v = st.secrets.get(name)
    except Exception:
        v = None
    return v or os.environ.get(name)


API_KEY, MODEL = secret("GEMINI_API_KEY"), secret("GEMINI_MODEL") or "gemini-3.8-flash"


@st.cache_resource
def get_conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = store.connect(DB_PATH)
    if store.is_empty(conn):
        sample.seed(conn, date.today())
    return conn


conn = get_conn()
today = date.today()


def days_label(d: date) -> str:
    n = (d - today).days
    return "closes today" if n == 0 else "closes tomorrow" if n == 1 else f"closes in {n} days" if n > 1 else f"closed {-n} days ago"


def show(obj):
    if hasattr(obj, "to_plotly_json"):
        st.plotly_chart(obj, width="stretch", config={"displaylogo": False})
    else:
        st.dataframe(obj, width="stretch", hide_index=True)


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("Placewise")
    view = st.radio("View as", ["Student", "Coordinator: add a drive", "Coordinator: dashboard", "Data & settings"])
    st.divider()
    st.caption("AI extraction: " + (f"**Gemini** ({MODEL})" if API_KEY else "**rule-based parser** (add a GEMINI_API_KEY secret to use Gemini)"))
    st.caption("Demo data: fictional companies and fake students.")

students = store.students(conn)
drives = store.drives(conn)
apps = store.applications(conn)


# ------------------------------------------------------------------ student view
def student_view():
    st.header("Your placement drives")
    if students.empty:
        st.info("No students loaded yet. A coordinator can upload the list under Data & settings.")
        return
    labels = {r.roll_no: f"{r.roll_no} · {r.name} ({r.branch}, CGPA {r.cgpa:.2f})" for r in students.itertuples()}
    roll = st.selectbox("Student (in a real rollout this is your login)", list(labels), format_func=labels.get)
    s = students.set_index("roll_no").loc[roll].to_dict() | {"roll_no": roll}
    mine = apps[apps.roll_no == roll].set_index("drive_id").status.to_dict() if len(apps) else {}

    eligible_open, ineligible, closed = [], [], []
    for d in drives:
        dl = date.fromisoformat(d["deadline"])
        ok, reasons = check(s, d)
        if dl < today:
            closed.append((d, ok))
        elif ok:
            eligible_open.append(d)
        else:
            ineligible.append((d, reasons))

    pending = [d for d in eligible_open if d["id"] not in mine]
    urgent = [d for d in pending if (date.fromisoformat(d["deadline"]) - today).days <= 2]
    c = st.columns(3)
    c[0].metric("Open drives you're eligible for", len(eligible_open))
    c[1].metric("Applied", sum(1 for d in eligible_open if mine.get(d["id"]) == "applied"))
    c[2].metric("Need action within 2 days", len(urgent))

    st.subheader("Open for you")
    if not eligible_open:
        st.write("Nothing open for you right now.")
    for d in eligible_open:
        dl = date.fromisoformat(d["deadline"])
        status = mine.get(d["id"])
        with st.container(border=True):
            top = st.columns([3, 1])
            top[0].markdown(f"**{d['company']}** · {d['role']}")
            top[0].caption(" · ".join(x for x in [f"{d['ctc_lpa']:g} LPA" if d.get("ctc_lpa") else None, d.get("location"),
                                                  rules_summary(d)] if x))
            urgent_flag = (dl - today).days <= 2 and not status
            top[1].markdown(f"{'⚠️ ' if urgent_flag else ''}**{days_label(dl).capitalize()}**  \n{dl:%d %b %Y}")
            b = st.columns([1.3, 1.3, 1, 3])
            if status == "applied":
                b[0].success("Applied ✓")
                if b[1].button("Undo", key=f"undo_{d['id']}_{roll}"):
                    store.set_application(conn, d["id"], roll, None); st.rerun()
            elif status == "not_interested":
                b[0].info("Not interested")
                if b[1].button("Undo", key=f"undo_{d['id']}_{roll}"):
                    store.set_application(conn, d["id"], roll, None); st.rerun()
            else:
                if d.get("apply_link"):
                    b[0].link_button("Open application", d["apply_link"])
                if b[1].button("Mark as applied", key=f"ap_{d['id']}_{roll}", type="primary"):
                    store.set_application(conn, d["id"], roll, "applied"); st.rerun()
                if b[2].button("Not interested", key=f"ni_{d['id']}_{roll}"):
                    store.set_application(conn, d["id"], roll, "not_interested"); st.rerun()

    with st.expander(f"Not eligible ({len(ineligible)}) and why"):
        if not ineligible:
            st.write("You're eligible for every open drive.")
        for d, reasons in ineligible:
            st.markdown(f"**{d['company']}** · {d['role']}: " + "; ".join(reasons))
    with st.expander(f"Closed drives ({len(closed)})"):
        for d, ok in closed:
            st.markdown(f"**{d['company']}** · {d['role']} · closed {date.fromisoformat(d['deadline']):%d %b} · "
                        + ({"applied": "you applied", "not_interested": "you passed"}.get(mine.get(d["id"]), "no response")
                           if ok else "not eligible"))


# ------------------------------------------------------------------ add a drive
def add_drive_view():
    st.header("Add a drive")
    st.caption("Paste the job description. AI drafts the eligibility rules; you check them and publish.")
    ss = st.session_state
    ss.setdefault("n", 0)
    if ss.pop("clear_jd", False):   # widget values can only be reset before the widget is drawn
        ss.jd = ""
    examples = {jd.splitlines()[0][:48]: jd for jd, _ in sample.sample_jds(today)}
    left, right = st.columns([1, 1], gap="large")
    with left:
        ex = st.selectbox("Or load an example JD", ["(none)", *examples])
        if ex != "(none)" and ss.get("loaded_example") != ex:
            ss.jd = examples[ex]; ss.loaded_example = ex
        jd = st.text_area("Job description", key="jd", height=320, placeholder="Paste the JD text or email here…")
        if st.button("Extract rules", type="primary", disabled=not (jd or "").strip()):
            with st.spinner("Reading the JD…"):
                fields, method, note = extract(jd, API_KEY, MODEL, today)
            ss.extracted, ss.method, ss.note, ss.jd_used = fields, method, note, jd
            ss.n += 1
    with right:
        if "extracted" not in ss:
            st.info("The extracted fields appear here for you to check.")
            return
        e, n = ss.extracted, ss.n
        st.markdown(f"**Check before publishing** · extracted by {'Gemini' if ss.method == 'gemini' else 'the rule-based parser'}")
        if ss.note:
            st.warning(ss.note)
        missing = [k for k, v in e.items() if v in (None, "") and k not in ("apply_link", "batch", "max_backlogs", "min_cgpa", "location")]
        if missing:
            st.caption("Not found in the JD: " + ", ".join(missing) + ". Fill these in.")
        company = st.text_input("Company", e["company"] or "", key=f"co_{n}")
        role = st.text_input("Role", e["role"] or "", key=f"ro_{n}")
        c1, c2 = st.columns(2)
        ctc = c1.number_input("CTC (LPA)", min_value=0.0, value=e["ctc_lpa"], step=0.5, key=f"ctc_{n}")
        min_cgpa = c2.number_input("Minimum CGPA (blank = none)", min_value=0.0, max_value=10.0, value=e["min_cgpa"],
                                   step=0.1, key=f"cg_{n}")
        branches = st.multiselect("Eligible branches (empty = all)", BRANCHES, default=e["branches"],
                                  format_func=lambda b: f"{b} · {BRANCH_NAMES[b]}", key=f"br_{n}")
        c3, c4 = st.columns(2)
        backlogs = c3.number_input("Max active backlogs (blank = no limit)", min_value=0, max_value=10,
                                   value=e["max_backlogs"], step=1, key=f"bl_{n}")
        batch = c4.number_input("Batch (blank = any)", min_value=2020, max_value=2035, value=e["batch"], step=1, key=f"ba_{n}")
        deadline = st.date_input("Deadline", value=date.fromisoformat(e["deadline"]) if e["deadline"] else None, key=f"dl_{n}")
        c5, c6 = st.columns(2)
        location = c5.text_input("Location", e["location"] or "", key=f"lo_{n}")
        link = c6.text_input("Application link", e["apply_link"] or "", key=f"li_{n}")

        final = {"company": company.strip() or None, "role": role.strip() or None, "ctc_lpa": ctc or None,
                 "min_cgpa": min_cgpa, "branches": branches,
                 "max_backlogs": int(backlogs) if backlogs is not None else None,
                 "batch": int(batch) if batch is not None else None,
                 "deadline": deadline.isoformat() if deadline else None,
                 "location": location.strip() or None, "apply_link": link.strip() or None}
        if not students.empty:
            n_ok = sum(check(s, final)[0] for s in students.to_dict("records"))
            st.metric("Students eligible under these rules", f"{n_ok} of {len(students)}")
        corrections = sample.count_corrections(e, final)
        st.caption(f"Fields you changed: {corrections}")
        problems = [x for x, ok in [("company", final["company"]), ("role", final["role"]), ("deadline", final["deadline"])] if not ok]
        if st.button("Publish drive", type="primary", disabled=bool(problems), key=f"pub_{n}"):
            store.add_drive(conn, final, ss.jd_used, ss.method, corrections)
            for k in ("extracted", "method", "note", "jd_used", "loaded_example"):
                ss.pop(k, None)
            ss.clear_jd = True
            st.success(f"Published {final['company']} · {final['role']}. Eligible students see it now.")
            st.rerun()
        if problems:
            st.caption("Needed before publishing: " + ", ".join(problems))


# ------------------------------------------------------------------ dashboard
def rate_chart(stats: pd.DataFrame) -> go.Figure:
    d = stats.sort_values("deadline", ascending=False)
    labels = [f"{r.company} · {'closed' if r.status == 'closed' else f'{r.days_left}d left'}" for r in d.itertuples()]
    fig = go.Figure(go.Bar(
        y=labels, x=d.rate, orientation="h", marker={"color": BLUE, "cornerradius": 4},
        text=[f"{r:.0%} ({a}/{e})" if e else "no eligible students" for r, a, e in zip(d.rate.fillna(0), d.applied, d.eligible)],
        textposition="outside", cliponaxis=False, textfont={"color": INK},
        hovertemplate="%{y}<br><b>%{x:.0%}</b> of eligible students applied<extra></extra>"))
    fig.add_vline(x=M.NORTH_STAR_TARGET, line={"color": MUTED, "width": 1, "dash": "dash"},
                  annotation_text=f"Target {M.NORTH_STAR_TARGET:.0%}", annotation_position="top",
                  annotation_font={"color": INK2, "size": 11})
    fig.update_layout(title={"text": "Eligible students who applied, by drive", "x": 0, "font": {"size": 15, "color": INK}},
                      font={"family": "system-ui, sans-serif", "color": INK2}, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      hoverlabel={"bgcolor": "#1f1f1e", "font": {"color": INK}},
                      height=90 + 46 * len(d), margin={"l": 8, "r": 60, "t": 56, "b": 8}, showlegend=False)
    fig.update_xaxes(range=[0, 1.15], tickformat=".0%", gridcolor=GRID, zeroline=False, linecolor=AXIS)
    fig.update_yaxes(showgrid=False)
    return fig


def dashboard_view():
    st.header("Coordinator dashboard")
    if not drives:
        st.info("No drives yet. Add one under 'Coordinator: add a drive'.")
        return
    stats = M.drive_stats(students, drives, apps, today)
    ns, n_elig = M.north_star(stats)
    silent = M.silent_students(students, drives, apps, today)
    open_n = int((stats.status == "open").sum())
    c = st.columns(4)
    c[0].metric("North Star · eligible application rate", f"{ns:.0%}" if ns is not None else "—",
                help=f"Applied ÷ eligible across closed drives ({n_elig} eligible student-drive pairs). "
                     f"Target {M.NORTH_STAR_TARGET:.0%} is a placeholder until last season's baseline is measured.")
    c[1].metric("Open drives", open_n)
    c[2].metric("Eligible but silent", len(silent), help="Eligible for at least one open drive, applied to none")
    c[3].metric("AI fields corrected per JD", f"{stats.fields_corrected.mean():.1f}",
                help="Fields the coordinator changed before publishing. Lower means the extraction is getting better.")

    show(rate_chart(stats))
    table = stats.assign(
        deadline=stats.deadline.map(lambda d: f"{d:%d %b}"), rate=stats.rate.map(lambda r: f"{r:.0%}" if pd.notna(r) else "—"),
    )[["company", "role", "deadline", "status", "eligible", "applied", "not_interested", "pending", "rate", "fields_corrected"]]
    show(table.rename(columns={"not_interested": "not interested", "fields_corrected": "AI fields corrected"}))

    st.subheader("Nudge list")
    open_drives = [d for d in drives if date.fromisoformat(d["deadline"]) >= today]
    if not open_drives:
        st.write("No open drives.")
    else:
        names = {d["id"]: f"{d['company']} · {d['role']} ({days_label(date.fromisoformat(d['deadline']))})" for d in open_drives}
        did = st.selectbox("Drive", list(names), format_func=names.get)
        d = next(x for x in open_drives if x["id"] == did)
        pend = M.pending_students(students, d, apps)
        st.write(f"**{len(pend)}** eligible students haven't applied or declined yet.")
        show(pend)
        st.download_button("Download nudge list (CSV)", pend.to_csv(index=False), f"nudge_{d['company'][:20]}.csv", "text/csv")
        msg = (f"Reminder: {d['company']} is hiring for {d['role']}. Applications close on "
               f"{date.fromisoformat(d['deadline']):%d %b}. You're eligible: check Placewise and apply"
               + (f" at {d['apply_link']}" if d.get("apply_link") else "") + ".")
        st.text_area("WhatsApp message to send them", msg, height=90)

    with st.expander(f"Eligible but silent ({len(silent)}): eligible for an open drive, applied to none"):
        show(silent)
        st.download_button("Download (CSV)", silent.to_csv(index=False), "silent_students.csv", "text/csv")


# ------------------------------------------------------------------ data & settings
def data_view():
    st.header("Data & settings")
    st.subheader("Students")
    st.write("Upload a CSV with the columns `roll_no, name, branch, cgpa, active_backlogs, batch`. "
             f"Branches use the codes {', '.join(BRANCHES)}. Uploading replaces the current list.")
    up = st.file_uploader("Student list (CSV)", type="csv")
    if up is not None and st.button("Replace student list"):
        try:
            n = store.replace_students(conn, pd.read_csv(up))
            st.success(f"Loaded {n} students."); st.rerun()
        except Exception as e:
            st.error(f"Couldn't load that file: {e}")
    st.caption("Collect only what eligibility needs, with the placement officer's approval. Don't put real student data on a public demo link.")

    st.subheader("Export")
    c = st.columns(3)
    c[0].download_button("Students (CSV)", students.to_csv(index=False), "students.csv", "text/csv")
    c[1].download_button("Drives (CSV)", pd.DataFrame(drives).drop(columns=["jd_text"], errors="ignore").to_csv(index=False),
                         "drives.csv", "text/csv")
    c[2].download_button("Applications (CSV)", apps.to_csv(index=False), "applications.csv", "text/csv")

    st.subheader("Gemini")
    st.write("To use Gemini for extraction, add `GEMINI_API_KEY` (and optionally `GEMINI_MODEL`) to the app's secrets: "
             "in Streamlit Community Cloud, **App settings → Secrets**; locally, `.streamlit/secrets.toml`. "
             "Without a key, the rule-based parser is used.")

    st.subheader("Reset demo")
    if st.button("Reset to the demo data", type="secondary"):
        store.reset(conn); sample.seed(conn, today); st.rerun()


{"Student": student_view, "Coordinator: add a drive": add_drive_view,
 "Coordinator: dashboard": dashboard_view, "Data & settings": data_view}[view]()
