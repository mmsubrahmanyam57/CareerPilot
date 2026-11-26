"""Career Guidance and Resume Feedback Chatbot - Streamlit dashboard.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import copy
import hashlib
import html
import json
import re
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import database as db
import accounts
import tools_ui as tools
from auth_ui import login_gate, signout, STYLE, DARK
import evaluation as ev
from ai_service import AIService, AIServiceError, get_api_key, get_default_model
from career_chatbot import CareerChatbot
from resume_analyzer import (REVIEW_SECTIONS, ResumeAnalyzer, ResumeError, compute_resume_id, extract_resume_lines,
                             feedback_dataframe, lines_dataframe, report_markdown)

st.set_page_config(page_title="CareerPilot - Career Guidance & Resume Feedback", page_icon="🎓",
                   layout="wide", initial_sidebar_state="expanded")

PAGES = ["🏠 Home", "💬 Career Guidance", "📄 Resume Analyzer", "🧑‍🏫 Human Review", "📊 AI vs Human Comparison"]

EXTRA = ["ATS Checker", "Job Matcher", "Skill Gap", "Learning Roadmap", "Mock Interview", "Resume Builder", "Learning Resources", "My Profile", "My History"]

CSS = """
<style>
.block-container {padding-top: 1.6rem; max-width: 1200px;}
.hero {background: linear-gradient(120deg, #4F46E5 0%, #7C3AED 55%, #06B6D4 100%); color: #fff;
       border-radius: 18px; padding: 2rem 2.2rem; margin-bottom: 1.2rem; box-shadow: 0 10px 30px rgba(79,70,229,.25);}
.hero h1 {color: #fff; margin: 0 0 .4rem 0; font-size: 2.1rem; line-height: 1.2;}
.hero p {color: #E0E7FF; margin: 0; font-size: 1.05rem;}
.card {background: #fff; border: 1px solid #E2E8F0; border-radius: 14px; padding: 1.1rem 1.2rem; height: 100%;
       box-shadow: 0 2px 8px rgba(15,23,42,.05);}
.card h4 {margin: 0 0 .4rem 0; color: #312E81;}
.card p {margin: 0; color: #475569; font-size: .92rem;}
.badge {display: inline-block; padding: .15rem .65rem; border-radius: 999px; font-size: .78rem; font-weight: 600;}
.badge-live {background: #DCFCE7; color: #166534;}
.badge-demo {background: #FEF3C7; color: #92400E;}
.side-brand {font-size: 1.25rem; line-height: 1.3; margin-bottom: .6rem;}
.side-brand span {font-size: .78rem; color: #64748B;}
div[data-testid="stMetric"] {background: #fff; border: 1px solid #E2E8F0; border-radius: 12px; padding: .7rem .9rem;}
@media (max-width: 768px) {
  .block-container {padding: 1rem .8rem;}
  .hero {padding: 1.2rem; border-radius: 14px;}
  .hero h1 {font-size: 1.45rem;}
  .hero p {font-size: .95rem;}
}
</style>
"""


# ----------------------------------------------------------------------------- helpers
def esc_md(text: object) -> str:
    """Escape markdown/HTML control characters so untrusted text is displayed literally."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~$&])", r"\\\1", str(text))


def init_state() -> None:
    ss = st.session_state
    ss.setdefault("nav", PAGES[0])
    ss.setdefault("model", get_default_model())
    ss.setdefault("store_excerpts", False)
    ss.setdefault("chat", CareerChatbot.new_session())
    ss.setdefault("resume", None)       # dict with parsed lines; the PDF itself is never kept
    ss.setdefault("ai_result", None)
    if not get_api_key():
        ss.demo_mode = True
    else:
        ss.setdefault("demo_mode", False)


def get_ai() -> AIService:
    actor=accounts.principal.get()
    guard=(lambda: accounts.consume_ai_quota(actor)) if actor and actor["role"]=="student" else None
    return AIService(model=st.session_state.model, demo_mode=st.session_state.demo_mode, request_guard=guard)


def goto(page: str) -> None:
    st.session_state.nav = page


def mode_banner(ai: AIService) -> None:
    if ai.live:
        st.markdown(f"<span class='badge badge-live'>● Live: {html.escape(ai.mode_label)}</span>", unsafe_allow_html=True)
    else:
        st.warning("**SIMULATED DEMO MODE** - no AI model is being used. Questions are scripted and results come from "
                   "simple rules. Do not treat this output as real AI feedback.")


def hero(title: str, subtitle: str) -> None:
    st.markdown(f"<div class='hero'><h1>{title}</h1><p>{subtitle}</p></div>", unsafe_allow_html=True)


def gauge(score: float, max_score: float, title: str) -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=score, title={"text": title},
        number={"suffix": f" / {max_score}"},
        gauge={"axis": {"range": [0, max_score]}, "bar": {"color": "#4F46E5"},
               "steps": [{"range": [0, max_score * .5], "color": "#FEE2E2"},
                         {"range": [max_score * .5, max_score * .75], "color": "#FEF3C7"},
                         {"range": [max_score * .75, max_score], "color": "#DCFCE7"}]}))
    fig.update_layout(height=260, margin=dict(l=20, r=20, t=50, b=10))
    return fig


# ----------------------------------------------------------------------------- sidebar
def sidebar(actor, pages) -> str:
    with st.sidebar:
        st.markdown("<div class='side-brand'>🎓 <b>CareerPilot</b><br><span>Career guidance &amp; resume feedback</span></div>",
                    unsafe_allow_html=True)
        st.write(actor["name"] + " · " + actor["role"].title())
        if st.button("Sign out", use_container_width=True): signout()
        st.toggle("Dark appearance", key="dark_ui")
        if st.session_state.get("dark_ui"): st.markdown(DARK, unsafe_allow_html=True)
        if st.session_state.nav not in pages: st.session_state.nav = pages[0]
        page = st.radio("Navigation", pages, key="nav", label_visibility="collapsed")
        st.divider()
        has_key = bool(get_api_key())
        st.toggle("Offline demo mode (simulated)", key="demo_mode", disabled=not has_key,
                  help="Runs without calling Gemini. All output is simulated and labelled as such.")
        if not has_key:
            st.caption("GEMINI_API_KEY not found in .env, so demo mode is forced.")
        st.text_input("Gemini model", key="model", disabled=os.getenv("APP_ENV","").lower()=="production", help="Any model name your API key can use, e.g. gemini-2.5-flash.")
        st.checkbox("Store original line excerpts in database", key="store_excerpts",
                    help="Off by default. When off, only line numbers, feedback and rewrites are saved.")
        ai = get_ai()
        css_class, text = ("badge-live", "Gemini live") if ai.live else ("badge-demo", "Simulated demo")
        st.markdown(f"<span class='badge {css_class}'>{text}</span>", unsafe_allow_html=True)
        if not ai.sdk_available and has_key:
            st.error("Package 'google-genai' is missing. Run: pip install -r requirements.txt")
        with st.expander("🛡️ Privacy & data"):
            st.caption("Uploaded PDFs are processed in memory and never saved. Resume text lives only in this browser "
                       "session. The database holds an anonymous resume ID, scores and feedback you choose to save.")
            if st.session_state.resume is not None:
                st.button("Remove resume from this session", on_click=clear_resume, key="sb_clear_resume")
    return page


def clear_resume() -> None:
    st.session_state.resume = None
    st.session_state.ai_result = None


# ----------------------------------------------------------------------------- home
def page_home(actor, pages):
    hero("Your career starts here", "A personal workspace to discover opportunities, improve your resume and build job-ready skills.")
    mode_banner(get_ai())
    stats = db.counts()
    for col, (label, value) in zip(st.columns(4), [("Resumes",stats['resumes']), ("AI reviews",stats['ai_reviews']), ("Human feedback",stats['human_reviews']), ("Evaluations",stats['evaluations'])]):
        col.metric(label,value)
    if actor["role"]=="student":
        saved=accounts.activities(actor)
        for col,kind in zip(st.columns(3),["Career guidance","Interview","Roadmap"]): col.metric(kind+" saved",sum(r["kind"]==kind for r in saved))
    st.subheader("Explore your workspace")
    options=[p for p in pages if p!=PAGES[0]]
    for i in range(0,len(options),3):
        for col,target in zip(st.columns(3),options[i:i+3]):
            with col, st.container(border=True):
                st.subheader(target)
                st.button("Open tool",key="open_"+target,on_click=goto,args=(target,),use_container_width=True)
    st.caption("All counts come from the current database workspace.")


# ----------------------------------------------------------------------------- career guidance
def render_recommendations(rec: dict) -> None:
    st.subheader("🎯 Your three recommended career paths")
    if rec.get("simulated"):
        st.warning("SIMULATED recommendations: produced by keyword matching, not by an AI model.")
    if rec.get("profile_summary"):
        st.info(rec["profile_summary"])
    rows = []
    for c in rec["careers"]:
        rows.append({"Career": c["title"], "Skills": "Already have", "Count": len(c["existing_skills"])})
        rows.append({"Career": c["title"], "Skills": "Still to learn", "Count": len(c["missing_skills"])})
    fig = px.bar(pd.DataFrame(rows), x="Career", y="Count", color="Skills", barmode="stack",
                 color_discrete_map={"Already have": "#10B981", "Still to learn": "#F59E0B"},
                 title="Skill coverage per career path")
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=-0.25))
    st.plotly_chart(fig)
    tabs = st.tabs([f"{i}. {c['title']}" for i, c in enumerate(rec["careers"], 1)])
    for tab, c in zip(tabs, rec["careers"]):
        with tab:
            st.markdown(f"**Fit:** {esc_md(c['fit'])}")
            st.markdown("#### Why it suits you")
            st.write(c["why_suitable"])
            left, right = st.columns(2)
            with left:
                st.markdown("#### ✅ Skills you already have")
                st.write("\n".join(f"- {esc_md(s)}" for s in c["existing_skills"]) or "_None identified from your answers yet._")
            with right:
                st.markdown("#### 🎯 Skills to develop")
                st.write("\n".join(f"- {esc_md(s)}" for s in c["missing_skills"]) or "_None identified._")
            st.markdown("#### 🗺️ Personalised learning roadmap")
            for phase in c["roadmap"]:
                with st.expander(f"{phase['phase']} - {phase['duration']}", expanded=True):
                    st.write(phase["focus"])
                    st.write("\n".join(f"- {a}" for a in phase["actions"]))


def page_career(actor) -> None:
    hero("Career Guidance Chatbot", "Answer one question at a time. After the interview you get three career paths and a roadmap.")
    ai = get_ai()
    mode_banner(ai)
    bot = CareerChatbot(ai)
    chat = st.session_state.chat
    bot.start(chat)

    prompt = st.chat_input("Type your answer here...", disabled=bot.is_complete(chat))
    if prompt:
        try:
            with st.spinner("Thinking..."):
                _, warning = bot.reply(chat, prompt)
            if warning:
                st.warning(warning)
        except ValueError as exc:
            st.error(str(exc))

    answered, total = len(chat["answers"]), bot.total_questions()
    top_left, top_right = st.columns([4, 1])
    top_left.progress(min(answered / total, 1.0), text=f"Interview progress: {answered}/{total} questions answered")
    if top_right.button("🔄 Restart"):
        st.session_state.chat = CareerChatbot.new_session()
        st.rerun()

    for message in chat["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(esc_md(message["content"]))

    if answered >= 3 and chat["recommendations"] is None:
        label = "✨ Generate my career recommendations" if answered >= total else "✨ Generate recommendations now (early)"
        if st.button(label, type="primary"):
            try:
                with st.spinner("Analysing your answers..."):
                    bot.recommend(chat)
            except (AIServiceError, ValueError) as exc:
                st.error(str(exc))
    if chat["answers"] and st.button("Save conversation and recommendations"):
        tools.save(actor,"Career guidance","Career interview",chat,("demo" if chat["recommendations"].get("simulated") else "gemini") if chat["recommendations"] else "conversation")
    if chat["recommendations"]:
        render_recommendations(chat["recommendations"])
        d1, d2 = st.columns(2)
        d1.download_button("⬇️ Download as Markdown", CareerChatbot.transcript_markdown(chat),
                           file_name="career_guidance.md", mime="text/markdown")
        d2.download_button("⬇️ Download as JSON", CareerChatbot.recommendations_json(chat),
                           file_name="career_recommendations.json", mime="application/json")


# ----------------------------------------------------------------------------- resume upload (shared)
def resume_uploader(key: str) -> dict | None:
    uploaded = st.file_uploader("Upload a PDF resume (max 10 MB, text-based PDF)", type=["pdf"], key=key,
                                help="The file is read in memory and is not saved to disk.")
    if uploaded is not None:
        data = uploaded.getvalue()
        signature = hashlib.sha256(data).hexdigest()
        current = st.session_state.resume
        if current is None or current["file_sig"] != signature:
            try:
                lines = extract_resume_lines(data)
            except ResumeError as exc:
                st.error(str(exc))
                return st.session_state.resume
            rid = compute_resume_id(lines)
            st.session_state.resume = {"file_sig": signature, "lines": lines, "resume_id": rid}
            st.session_state.ai_result = None
    resume = st.session_state.resume
    if resume is None:
        return None
    st.text_input("Label for this resume (avoid real names)", value=f"Resume-{resume['resume_id'][:6]}",
                  key=f"label_{resume['resume_id']}", max_chars=60)
    resume["label"] = st.session_state.get(f"label_{resume['resume_id']}") or f"Resume-{resume['resume_id'][:6]}"
    st.caption(f"Resume ID `{resume['resume_id']}` · {len(resume['lines'])} lines · "
               f"{max(l.page for l in resume['lines'])} page(s). The same resume always gets the same ID, so human "
               f"reviewers can match it later.")
    return resume


def show_lines(resume: dict, key: str) -> None:
    df = lines_dataframe(resume["lines"])
    section = st.selectbox("Filter by detected section", ["All"] + sorted(df["Section"].unique()), key=key)
    if section != "All":
        df = df[df["Section"] == section]
    st.dataframe(df, hide_index=True, height=320)


# ----------------------------------------------------------------------------- resume analyzer
def render_analysis(result: dict, resume: dict) -> None:
    if result["simulated"]:
        st.warning("**SIMULATED analysis** (rule-based). Switch off demo mode and add a Gemini key for real AI feedback.")
    c1, c2 = st.columns([1, 1.4])
    with c1:
        st.plotly_chart(gauge(result["total_score"], result["max_total"], "Overall resume score"))
    with c2:
        st.markdown("#### Summary")
        st.write(result["overall_summary"])
        if result["strengths"]:
            st.markdown("**Strengths:** " + "; ".join(esc_md(s) for s in result["strengths"]))
        st.caption(f"{result['stats']['feedback_verified']} feedback item(s) verified against the extracted text · "
                   f"{result['stats']['feedback_rejected']} discarded")

    st.markdown("#### Section-wise scores")
    for s in result["sections"]:
        st.progress(s["score"] / s["max_score"], text=f"{s['name']}: {s['score']} / {s['max_score']}")
        if s["justification"]:
            st.caption(s["justification"])
    df = pd.DataFrame(result["sections"])
    df["Percent"] = (100 * df["score"] / df["max_score"]).round(0)
    fig = px.bar(df, x="Percent", y="name", orientation="h", range_x=[0, 100], text="score",
                 labels={"name": "", "Percent": "% of section maximum"}, title="Score by section (%)")
    fig.update_traces(marker_color="#4F46E5")
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=50, b=10), yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig)

    st.markdown("#### Line-by-line feedback")
    items = result["line_feedback"]
    if not items:
        st.info("No verified line-level feedback was produced.")
    f1, f2 = st.columns(2)
    sections = f1.multiselect("Sections", sorted({i["section"] for i in items}), default=None, placeholder="All sections")
    severities = f2.multiselect("Severity", ["high", "medium", "low"], default=None, placeholder="All severities")
    icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    for item in items:
        if (sections and item["section"] not in sections) or (severities and item["severity"] not in severities):
            continue
        title = f"{icon.get(item['severity'], '⚪')} Line {item['line_id']} · page {item['page']} · {item['section']} - {item['issue'][:70]}"
        with st.expander(esc_md(title)):
            st.caption(f"Original line (page {item['page']}, line {item['line_on_page']} on page) · status: {item['status']}")
            st.code(item["original_line"], language=None)
            st.markdown("**Issue:** " + esc_md(item["issue"]))
            st.markdown("**Why it is a problem:** " + esc_md(item["explanation"]))
            st.caption("Suggested rewrite (replace [bracketed] parts with true details only)")
            st.code(item["suggested_rewrite"], language=None)
            for flag in item["flags"]:
                st.warning(flag)
    if result["rejected_feedback"]:
        with st.expander(f"⚠️ {len(result['rejected_feedback'])} discarded item(s) - quoted line not found in the resume"):
            st.caption("These AI items quoted text that does not exist in the extracted resume, so they are not shown as feedback.")
            for item in result["rejected_feedback"]:
                st.text(f"[{item['status']}] {item['issue']}")

    st.markdown("#### Download & save")
    label = resume["label"]
    d1, d2, d3 = st.columns(3)
    d1.download_button("⬇️ Report (Markdown)", report_markdown(result, label), file_name="resume_feedback.md", mime="text/markdown")
    d2.download_button("⬇️ Feedback (CSV)", ev.to_csv_bytes(feedback_dataframe(result)), file_name="resume_feedback.csv", mime="text/csv")
    d3.download_button("⬇️ Full result (JSON)", json.dumps(result, indent=2, ensure_ascii=False),
                       file_name="resume_feedback.json", mime="application/json")
    if st.button("💾 Save AI feedback for the AI-vs-Human comparison"):
        payload = copy.deepcopy(result)
        payload["rejected_feedback"] = []
        if not st.session_state.store_excerpts:
            for item in payload["line_feedback"]:
                item["original_line"] = ""
        try:
            db.save_ai_review(result["resume_id"], label, result["model"], result["mode"], result["total_score"], payload)
            st.success("Saved. Resume text was not stored" + ("" if st.session_state.store_excerpts else ", and line excerpts were left out") + ".")
        except Exception as exc:  # noqa: BLE001
            st.error("Could not save to the database. Check configuration.")


def page_analyzer() -> None:
    hero("AI Resume Analyzer", "100-point rubric, exact original lines, explanations and concrete rewrites - verified against your text.")
    ai = get_ai()
    mode_banner(ai)
    resume = resume_uploader("analyzer_upload")
    if resume is None:
        st.info("Upload a text-based PDF resume to begin.")
        return
    with st.expander("📃 Extracted text with page and line numbers", expanded=False):
        show_lines(resume, "analyzer_filter")
    if st.button("🔍 Analyze resume", type="primary"):
        try:
            with st.spinner("Analyzing resume and verifying quoted lines..."):
                st.session_state.ai_result = ResumeAnalyzer(ai).analyze(resume["lines"])
        except (AIServiceError, ResumeError) as exc:
            st.error(str(exc))
    result = st.session_state.ai_result
    if result and result["resume_id"] == resume["resume_id"]:
        render_analysis(result, resume)


# ----------------------------------------------------------------------------- human review
def page_human() -> None:
    hero("Human Reviewer", "Review the resume independently. AI feedback is hidden on this page.")
    resume = resume_uploader("human_upload")
    if resume is None:
        st.info("Upload the same PDF resume the AI analyzed (or any resume you want to review).")
        return
    if resume["resume_id"] not in {r["resume_id"] for r in db.list_resumes()}:
        st.error("This PDF does not match a saved resume in the selected workspace."); return
    lines = resume["lines"]
    with st.expander("📃 Resume text with page and line numbers", expanded=True):
        show_lines(resume, "human_filter")

    st.subheader("Add review feedback")
    reviewer = st.session_state["auth_uid"]
    st.caption("Review attributed to your authenticated reviewer ID.")
    line_no = st.number_input("Line number (0 = general feedback)", min_value=0, max_value=len(lines), value=0, step=1,
                              key=f"human_line_no_{resume['resume_id']}")
    selected = lines[int(line_no) - 1] if line_no > 0 else None
    if selected is not None:
        st.caption(f"Selected line {selected.line_id} (page {selected.page}, detected section: {selected.section})")
        st.code(selected.text, language=None)
    with st.form("human_form", clear_on_submit=True):
        section = st.selectbox("Section name *", REVIEW_SECTIONS)
        feedback = st.text_area("Feedback / problem found *", height=90)
        explanation = st.text_area("Explanation (why is this a problem?)", height=90)
        rewrite = st.text_area("Suggested rewrite (use only facts from the resume)", height=90)
        submitted = st.form_submit_button("💾 Save review item", type="primary")
    if submitted:
        if not reviewer.strip():
            st.error("Please enter a reviewer name or ID.")
        elif not feedback.strip():
            st.error("Please describe the feedback.")
        else:
            try:
                db.add_human_review(resume["resume_id"], resume["label"], reviewer, section, int(line_no),
                                    selected.page if selected else None,
                                    selected.text if (selected and st.session_state.store_excerpts) else None,
                                    feedback, explanation, rewrite)
                st.success("Review item saved.")
            except Exception as exc:  # noqa: BLE001
                st.error("Could not save review. Check database configuration.")

    st.subheader("Saved review items for this resume")
    rows = db.list_human_reviews(resume["resume_id"], reviewer=reviewer)
    if not rows:
        st.info("No human feedback saved yet.")
        return
    df = pd.DataFrame(rows)[["id", "reviewer", "section", "line_no", "page", "feedback", "explanation", "suggested_rewrite", "created_at"]]
    st.dataframe(df, hide_index=True)
    c1, c2 = st.columns([2, 1])
    c1.download_button("⬇️ Download human feedback (CSV)", ev.to_csv_bytes(df), file_name="human_feedback.csv", mime="text/csv")
    with c2:
        delete_id = st.selectbox("Delete item ID", df["id"].tolist(), key="delete_human_id")
        if st.button("🗑️ Delete"):
            db.delete_human_review(int(delete_id))
            st.rerun()


# ----------------------------------------------------------------------------- comparison
def scoring_widgets(prefix: str) -> dict[str, int | None]:
    scores: dict[str, int | None] = {}
    for crit in ev.CRITERIA:
        guide = "  \n".join(f"{k} = {v}" for k, v in crit["guide"].items())
        scores[crit["key"]] = st.radio(crit["label"], [0, 1, 2], index=None, horizontal=True,
                                       key=f"{prefix}_{crit['key']}", help=guide)
    return scores


def tab_score() -> None:
    resumes = [r for r in db.list_resumes() if r["ai_mode"] or r["human_count"]]
    if not resumes:
        st.info("Nothing to score yet. Save AI feedback (Resume Analyzer) and human feedback (Human Review) for a resume first.")
        return
    labels = {r["resume_id"]: f"{r['label']} ({r['resume_id']})" for r in resumes}
    rid = st.selectbox("Resume", list(labels), format_func=labels.get)
    ai_row = db.get_ai_review(rid)
    human_rows = db.list_human_reviews(rid)
    reviewers = db.list_reviewers(rid)

    if ai_row is None:
        st.warning("No AI feedback has been saved for this resume.")
    elif ai_row["mode"] == "demo":
        st.warning("The saved AI feedback came from the SIMULATED demo mode. Scores for it can be excluded in the aggregate view.")
    if not human_rows:
        st.warning("No human feedback has been saved for this resume.")

    ai_items = ai_row["result"]["line_feedback"] if ai_row else []
    facts = ev.evidence_summary(ai_items, human_rows)
    st.markdown("##### Objective facts (for orientation only - these are NOT scores)")
    m = st.columns(4)
    m[0].metric("AI feedback items", facts["ai_items"])
    m[1].metric("Human feedback items", facts["human_items"])
    m[2].metric("Lines flagged by both", len(facts["lines_in_both"]))
    m[3].metric("Sections flagged by both", len(facts["sections_in_both"]))

    left, right = st.columns(2)
    with left:
        with st.expander("🤖 AI feedback", expanded=False):
            if ai_items:
                st.dataframe(pd.DataFrame(ai_items)[["line_id", "section", "issue", "explanation", "suggested_rewrite"]], hide_index=True)
            else:
                st.caption("None saved.")
    with right:
        with st.expander("🧑‍🏫 Human feedback", expanded=False):
            if human_rows:
                st.dataframe(pd.DataFrame(human_rows)[["reviewer", "section", "line_no", "feedback", "explanation", "suggested_rewrite"]], hide_index=True)
            else:
                st.caption("None saved.")
    if ai_row is None or not human_rows:
        return

    st.markdown("##### Manual scoring (0 = poor, 1 = partial, 2 = fully meets the criterion)")
    st.caption("Hover over the (?) next to each criterion to see what 0, 1 and 2 mean. Scores are never pre-filled or automated.")
    with st.expander("Scoring rubric"):
        st.table(pd.DataFrame([{"Criterion": c["label"], "0": c["guide"][0], "1": c["guide"][1], "2": c["guide"][2]} for c in ev.CRITERIA]))
    evaluator = st.session_state["auth_uid"]
    st.caption("Scores attributed to your authenticated evaluator ID.")
    reviewer = st.selectbox("Human reviewer being scored", reviewers, key=f"reviewer_sel_{rid}")
    a, h = st.columns(2)
    with a:
        st.markdown("#### 🤖 AI feedback")
        ai_scores = scoring_widgets(f"ai_{rid}")
    with h:
        st.markdown("#### 🧑‍🏫 Human feedback")
        hu_scores = scoring_widgets(f"hu_{rid}_{reviewer}")
    notes = st.text_area("Notes (optional)", key=f"notes_{rid}", height=70)
    if st.button("💾 Save scores", type="primary", key=f"save_scores_{rid}"):
        if not evaluator.strip():
            st.error("Please enter the evaluator name or ID.")
        elif any(v is None for v in [*ai_scores.values(), *hu_scores.values()]):
            st.error("Please choose a score (0, 1 or 2) for every criterion for both AI and human feedback.")
        else:
            try:
                db.save_evaluation(rid, "ai", "", evaluator, ev.validate_scores(ai_scores), notes, ai_mode=ai_row["mode"])
                db.save_evaluation(rid, "human", reviewer, evaluator, ev.validate_scores(hu_scores), notes)
                st.success(f"Saved. AI total {sum(ai_scores.values())}/10 · Human total {sum(hu_scores.values())}/10.")
            except Exception as exc:  # noqa: BLE001
                st.error("Could not save scores. Check database configuration.")


def tab_aggregate() -> None:
    df_all = ev.evaluations_dataframe(db.list_evaluations())
    if df_all.empty:
        st.info("No evaluations have been scored yet, so there is nothing to chart. Nothing is estimated or fabricated.")
        return
    include_sim = st.toggle("Include evaluations of SIMULATED (demo-mode) AI feedback", value=False)
    df = ev.filter_real_ai(df_all, include_sim)
    if df.empty:
        st.warning("All saved evaluations involve SIMULATED AI feedback. Turn the switch on to view them.")
        return
    if include_sim and (df["ai_mode"] == "demo").any():
        st.warning("Some AI results below come from the simulated demo mode and are not real AI output.")
    avg = ev.average_by_source(df)
    paired = ev.paired_totals(df)
    k = st.columns(4)
    k[0].metric("Resumes evaluated", df["resume_id"].nunique())
    k[1].metric("Evaluation records", len(df))
    k[2].metric("Average AI total (/10)", f"{avg.loc['AI', 'total']:.2f}" if "AI" in avg.index else "n/a")
    k[3].metric("Average Human total (/10)", f"{avg.loc['Human', 'total']:.2f}" if "Human" in avg.index else "n/a")
    for source in avg.index:
        st.progress(float(avg.loc[source, "total"]) / ev.MAX_TOTAL, text=f"{source}: average {avg.loc[source, 'total']:.2f} / {ev.MAX_TOTAL}")
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(ev.criteria_bar_chart(avg))
    with c2:
        st.plotly_chart(ev.radar_chart(avg))
    if not paired.empty:
        st.plotly_chart(ev.totals_chart(paired))
        st.dataframe(paired, hide_index=True)
    else:
        st.info("Paired totals appear once the same evaluator has scored both AI and human feedback for a resume.")
    st.markdown("##### Average scores per criterion")
    st.dataframe(avg.rename(columns={**ev.CRITERIA_LABELS, "total": "Total (/10)"}))
    st.markdown("##### All evaluation records")
    export = df.drop(columns=["id"]).rename(columns=ev.CRITERIA_LABELS)
    st.dataframe(export, hide_index=True)
    c3, c4 = st.columns([2, 1])
    c3.download_button("⬇️ Export all evaluations (CSV)", ev.to_csv_bytes(export), file_name="ai_vs_human_evaluation.csv", mime="text/csv")
    c3.download_button("⬇️ Export averages (CSV)", ev.to_csv_bytes(avg.reset_index().rename(columns=ev.CRITERIA_LABELS)),
                       file_name="ai_vs_human_averages.csv", mime="text/csv")
    with c4:
        delete_id = st.selectbox("Delete evaluation record ID", df["id"].tolist(), key="delete_eval_id")
        if st.button("🗑️ Delete record"):
            db.delete_evaluation(int(delete_id))
            st.rerun()


def page_compare() -> None:
    hero("AI vs Human Comparison", "Score both feedback sets manually on five criteria (0-2 each, total 10) and compare.")
    t1, t2 = st.tabs(["📝 Score a resume", "📈 Aggregate results"])
    with t1:
        tab_score()
    with t2:
        tab_aggregate()


# ----------------------------------------------------------------------------- main
def main() -> None:
    # Streamlit Secrets are read only on the server. Never render their values.
    try:
        for key in ('GEMINI_API_KEY','GEMINI_MODEL','DATABASE_URL','APP_ENV','AI_DAILY_USER_LIMIT','AI_DAILY_GLOBAL_LIMIT'):
            value=st.secrets.get(key)
            if value is not None: os.environ[key]=str(value)
    except (FileNotFoundError, KeyError):
        pass
    except Exception as exc:
        if 'not found' not in str(exc).lower() and 'no secrets' not in str(exc).lower():
            st.error('Invalid server secrets configuration.'); return
    st.markdown(CSS+STYLE, unsafe_allow_html=True)
    try:
        actor=login_gate()
    except Exception:
        st.error("Account database unavailable. Check configuration."); return
    if not actor: return
    init_state()
    role=actor['role']
    target=None
    if role!='student':
        with st.sidebar:
            options={u['id']:u['name']+' · '+u['id'][:8] for u in accounts.users(actor) if u['role']=='student' and u['shared']}
            if role=='admin': options={'legacy':'Legacy local research records',**options}
            if not options:
                st.info("No student has shared a review workspace yet.")
                if st.button("Sign out"): signout()
                return
            target=st.selectbox("Review workspace",list(options),format_func=options.get)
            if st.session_state.get('selected_workspace')!=target:
                clear_resume(); st.session_state.selected_workspace=target
    pages=([PAGES[0],PAGES[1],PAGES[2]]+EXTRA if role=='student' else [PAGES[3]] if role=='reviewer' else ['Admin dashboard',PAGES[4]])
    try:
        with accounts.authorized_workspace(actor,target):
            db.init_db()
            page=sidebar(actor,pages)
            ai=get_ai()
            if role=='student' and page in [PAGES[1],PAGES[2],"Mock Interview"] and ai.live:
                if not st.checkbox("I consent to sending the information I enter on this page to Google Gemini for AI processing.",key='consent_'+page):
                    st.info("Consent is required for live AI. You can use offline demo mode instead."); return
            routes={PAGES[0]:lambda:page_home(actor,pages),PAGES[1]:lambda:page_career(actor),PAGES[2]:page_analyzer,PAGES[3]:page_human,PAGES[4]:page_compare,
                    'ATS Checker':lambda:tools.page_match(actor,True),'Job Matcher':lambda:tools.page_match(actor),'Skill Gap':lambda:tools.page_gap(actor),'Learning Roadmap':lambda:tools.page_roadmap(actor),'Mock Interview':lambda:tools.page_interview(actor,ai),'Resume Builder':lambda:tools.page_builder(actor,ai),'Learning Resources':tools.page_courses,'My Profile':lambda:tools.page_profile(actor),'My History':lambda:tools.page_history(actor,db)}
            if page=='Admin dashboard':
                hero("Administration", "Account directory and selected workspace statistics")
                members=accounts.users(actor); st.metric('Registered students',sum(u['role']=='student' for u in members))
                q=st.text_input('Search account names'); filtered=[u for u in members if q.lower() in u['name'].lower()]; st.dataframe(pd.DataFrame(filtered),hide_index=True)
                st.subheader('Selected workspace'); stats=db.counts()
                for col,(k,v) in zip(st.columns(4),stats.items()): col.metric(k.replace('_',' ').title(),v)
                st.bar_chart(pd.Series(stats)); st.caption('Workspace counts are not site-wide totals. Student sharing is opt-in.')
            else: routes[page]()
    except PermissionError:
        st.error('Access denied. Sign in again or select an authorized workspace.')
    except Exception:
        st.error('This operation could not be completed. Check the local configuration and try again. No secret values are shown.')
    st.divider(); st.caption("Academic prototype. AI output may be inaccurate. Do not upload resumes without permission.")

if __name__ == '__main__':
    main()
