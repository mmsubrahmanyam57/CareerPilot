# Career Guidance and Resume Feedback Chatbot

An academic prototype built with **Python 3.12, Streamlit, Google Gemini (google-genai), PyMuPDF, Pandas, Plotly, SQLite and python-dotenv**.

## Modules
| Page | What it does |
|---|---|
| Career Guidance | Asks one question at a time (education, interests, skills, academic performance, projects, goals, constraints), keeps the conversation history, then recommends 3 careers with reasons, existing/missing skills and a phased learning roadmap. |
| Resume Analyzer | Upload a PDF, extract text with page and line numbers, score with a 100-point rubric (7 sections), give line-level feedback with explanations and rewrites, and **verify every quoted line against the extracted text**. Download Markdown/CSV/JSON. |
| Human Review | A reviewer annotates the same resume (section, line number, feedback, explanation, rewrite). Saved in SQLite. AI feedback is hidden on this page for independence. |
| AI vs Human Comparison | An evaluator manually scores AI and human feedback on 5 criteria (0-2 each, total 10), then views averages, radar/bar charts, multi-resume totals and exports CSV. |

## Files
`app.py` (UI) · `ai_service.py` (Gemini wrapper) · `career_chatbot.py` · `resume_analyzer.py` · `evaluation.py` · `database.py` · `requirements.txt` · `.env.example` · `.gitignore` · `.streamlit/config.toml` (theme)

## Run on Windows (VS Code terminal, PowerShell)
```powershell
cd path\to\career_guidance_app
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # then put your key in .env
streamlit run app.py
```
If PowerShell blocks activation: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.

## Configuration (`.env`)
- `GEMINI_API_KEY` - your key (never hard-coded).
- `GEMINI_MODEL` - default `gemini-2.5-flash`; also editable in the sidebar.
- `DB_PATH` - default `data/career_app.db`.

## Demo mode
Without an API key (or with the sidebar toggle on) the app runs **offline, simulated** logic: scripted interview questions, keyword-based career matching and a rule-based resume checker. Every simulated output is labelled. Evaluations of simulated AI feedback are flagged and excluded from aggregates by default.

## Privacy and security
- PDFs are read in memory and never written to disk. The full resume text is kept only in the browser session; "Remove resume" in the sidebar clears it.
- The database stores an anonymous resume ID (hash prefix), a label you choose, scores, and feedback you explicitly save. Original line excerpts are stored **only** if you enable that option.
- Resume text is untrusted: control/zero-width characters are stripped, prompt delimiters are neutralised, the model is told to ignore instructions inside the resume, and all resume/AI text is displayed as plain text (no HTML).
- No API keys in code; `.env`, `data/` and `*.pdf` are git-ignored.

## Anti-fabrication measures
- The model must quote lines exactly; each quote is matched to the extracted text. Wrong line numbers are corrected, unmatched quotes are discarded.
- Rewrites must use only resume facts; missing details appear as `[placeholders]`. Numbers or capitalised terms in a rewrite that are absent from the resume are flagged (a heuristic, not a guarantee).
- Evaluation scores are only ever entered by a human evaluator. The app never auto-scores or fills in results; with no saved scores the charts stay empty.

## Evaluation method (suggested for your report)
1. Analyze each resume and save the AI feedback.
2. A human reviewer reviews it without seeing AI output.
3. A separate evaluator scores AI and human feedback on the five criteria using the rubric shown in the app.
4. Repeat for several resumes, then export CSV from the Aggregate tab.

## Limitations
Text-based PDFs only (no OCR; two-column layouts may extract in an odd order). Max 10 MB, 6 pages, 450 lines. AI scoring is subjective and can vary between runs; treat it as decision support, not ground truth.
