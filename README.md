# CareerPilot Advanced

Upgrade of the original Career Guidance and Resume Feedback Chatbot. Python 3.12, Streamlit, Gemini, PyMuPDF, Pandas, Plotly, SQLAlchemy PostgreSQL connection, SQLite locally, ReportLab PDF export.

## 1. Upgrade the existing Windows project (do not replace your backup)

1. Stop Streamlit (`Ctrl+C` in its terminal). Keep a backup of your original folder and its database.
2. Extract this ZIP into Downloads. Copy the CONTENTS of the `CareerPilot_Advanced` folder into your existing `CareerGuidanceChatbot` folder. Replace matching source files only. Do not replace `.env`, `venv/`, `data/` or `.git/`. The ZIP does not include these. Do not upload a backup containing secrets.
3. Open the original folder in VS Code. In PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

If the environment is not present: `py -3.12 -m venv venv` and activate as above. You may also call `venv\Scripts\python.exe` directly without activation. `requirements.txt` includes SQLAlchemy, psycopg and ReportLab in addition to existing dependencies.
4. Keep your existing `.env` with `GEMINI_API_KEY=...`. Optional `GEMINI_MODEL` specifies an available model for your key. Rotate any API key previously exposed in screenshots. Never print or share it.
5. Create local privileged accounts with these commands. Each prompts for a password twice (10+ characters). Pick unique passwords. Nothing is hardcoded.

```powershell
python setup_accounts.py --role admin --email admin@careerpilot.example --name "CareerPilot Admin"
python setup_accounts.py --role reviewer --email reviewer@careerpilot.example --name "CareerPilot Reviewer"
```

Use the website's Create account tab for a student, or run `python setup_accounts.py --role student --email student@careerpilot.example --name "Demo Student"`. These example addresses are for local testing; use your own real accounts for deployment. Passwords are hashed using salted PBKDF2-SHA256 (600,000 iterations), not stored in plaintext. There are no pre-installed demo accounts.
6. Run `python -m streamlit run app.py` or double-click `StartProject.bat`. Open http://localhost:8501. Select Create account or Sign in.

## 2. Roles and review workflow

- **Student:** landing page, private dashboard, career chat, resume analysis, ATS checker, job matcher, skill gap, roadmap with progress, mock interview, resume builder, learning resources, profile and history. Save results explicitly using the Save buttons. Reload history after logout/restart. New browser sessions may require sign-in again; this is intentional.
- **Reviewer:** see only student workspaces whose owners opt in to sharing, upload the same text-based PDF supplied independently by the student, add feedback against a saved resume, and view/delete only own feedback. AI results are not available to reviewers. No uploaded PDF is stored by default.
- **Admin/evaluator:** account directory, selected-workspace counts and manual AI vs Human comparison with the original five-criterion rubric, charts and CSV export. For a fair study the evaluator and reviewer must be different people. Admin account creation is a trusted CLI action. Public registration creates student accounts only. There is no self-service password reset or automatic reviewer assignment. Sharing opts in to authorized reviewer/admin access to the entire resume-review workspace; other student tool histories are not shared in the UI.

Example test workflow:
1. Register and sign in as student, consent to Gemini processing or choose offline simulation. Upload a fictional text-based PDF in Resume Analyzer. Analyze and **Save AI feedback**. Career chat results use the **Save conversation and recommendations** button. Each additional tool has a save action where applicable.
2. My Profile: opt in to sharing and save. Log out. Log in as Reviewer, select student workspace, upload the identical PDF and submit independent review items. Use a fictional or consented resume. The reviewer receives the PDF separately; no file is transmitted through the app to reviewers.
3. Log out; sign in as Admin. Select shared student workspace. Open AI vs Human Comparison, score both feedback sets manually, save. Repeat for multiple resumes in that workspace. Simulated scores are excluded by default. Admin metrics are workspace-specific, not global counts, except for the account directory/student count.
4. Sign in again as student: My History displays persisted AI reviews, human reviews, evaluation rows and other saved results. Edit profile, update roadmap and save progress, or delete history items. Restart the server and confirm records remain. Register a second student and confirm the first student's records are not visible.

## 3. Local database and migration

The original `data/career_app.db` is preserved in place, accessible to Admin through **Legacy local research records**. It is not assigned automatically to any new account because ownership cannot be inferred. Existing old SQLite schema is used unchanged; new account and workspace tables are created automatically, without destructive migrations. New records use `data/accounts.db` for users and `data/u_<random-id>.db` per user for reviews and activities. Inspect via DB Browser for SQLite locally; do not share those files or copy password hashes to a report. Stop the server before backing up databases. `DB_PATH` controls the legacy file and parent data directory. `data/` must be excluded from Git.

PostgreSQL uses an account schema and isolated workspace schemas (SQLAlchemy connection, parameterized SQL); the configured database role needs permission to create schemas and tables. This is a prototype architecture, not a substitute for a production security audit. PostgreSQL integration and migration require a real database test.

## 4. GitHub update (same repository)

First verify local functionality and make sure `.gitignore` ignores `.env`, `venv/`, `data/`, `.streamlit/secrets.toml`, private PDF files, ZIPs and database files. In the existing Git repository:

```powershell
git add .
git status
```

Inspect the staged list and ensure no secrets, private resume data, or local databases are staged. Then:

```powershell
git commit -m "Upgrade CareerPilot with authentication and career tools"
git push
```

Do not run `git init` or create a new remote again. The existing remote and branch are retained. `.env.example` contains only placeholders. Do not add credentials to source or README.

## 5. Public deployment checklist

Do this only after local login, permissions, resume review, database and AI tests. Cloud deployment has NOT been performed by the ZIP creator.

1. Create a PostgreSQL database with a hosted provider. Obtain its PostgreSQL connection string, with SSL required, and check that the database account can create schemas. Use a fresh database for this project. Hosting and database availability/limits depend on the provider and plan.
2. Create cloud admin and reviewer accounts from a trusted local terminal by temporarily setting `DATABASE_URL` to the cloud connection string in a local environment file (not GitHub). Run the same `setup_accounts.py` commands. Use unique non-demo production credentials. Alternatively import consented local records BEFORE creating cloud accounts (see next section). Remove the cloud URL from the local `.env` afterwards if you wish to resume local SQLite use.
3. Push tested code to your private GitHub repository. Go to https://share.streamlit.io/ and connect GitHub. Create an app using your repository, `main` branch and `app.py` as entry point. Select Python 3.12 if available. Use the App URL field to select an available name, e.g. `your-chosen-name.streamlit.app`. This is a preview, not a reserved URL. Streamlit documentation: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app
4. Add the following as **server-side Secrets** in the app settings, replacing placeholders. Never put them in GitHub:

```toml
GEMINI_API_KEY = "YOUR_NEW_PRIVATE_KEY"
GEMINI_MODEL = "YOUR_AVAILABLE_GEMINI_MODEL"
DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require"
APP_ENV = "production"
AI_DAILY_USER_LIMIT = "40"
AI_DAILY_GLOBAL_LIMIT = "300"
```

Root-level secrets are loaded into server environment variables. Production mode requires PostgreSQL, so a missing DB URL fails closed instead of silently storing cloud records in ephemeral SQLite. Select public app sharing only when the authentication/authorization checks and privacy notice have been verified. The GitHub repository can remain private. The public URL is generated by Streamlit, not by this project. Hosting may sleep or suspend inactive apps and Gemini calls require network access. Check your Gemini billing and quota configuration separately. Application logical AI request limits reduce abuse but do not guarantee zero costs (SDK retries and provider billing remain separate). Do not expose the prototype to unrestricted public traffic without further security/rate-limit testing.
5. Deploy, test the URL from another browser, and run the complete role workflow. Verify saved records remain after reboot. Public app sharing and repository permissions are separate. For subsequent tested updates, commit and push to the same branch.

### Optional: one-time import of local records into an empty cloud database

Only migrate data you are authorized to transfer, with student consent and a verified backup. Stop the local app. Set `DATABASE_URL` securely and use a new empty cloud database. Do not first create accounts there if importing existing accounts. Run `python cloud_migrate.py` for a dry run listing file count; then `python cloud_migrate.py --apply` for the import. The script attempts a single transaction, refuses to overwrite non-empty target tables, copies password hashes and workspace records (not uploaded PDFs), and preserves local files. This script is syntax-checked but not verified against a real PostgreSQL service. Test against a disposable PostgreSQL database before using it for real records. If you only need a new prototype, create fresh cloud accounts instead. Local and cloud records do not otherwise sync automatically.

## 6. Additional tools and limitations

- ATS and job matching use explicitly labelled heuristic keyword/section matching, not a real employer ATS. Skills use a curated role checklist; course links point to official docs where mapped (not live verified course inventories). Roadmaps are weekly templates with persisted progress.
- Mock interview questions are scripted per category/role; Gemini can generate coaching feedback, explanations and sample answers after consent. Resume Builder exports a basic single-column PDF and optionally requests Gemini suggestions for summary/projects only. It is not a drag-and-drop resume editor. PDF export is best for Latin text.
- Resume Analyzer preserves the original exact-line verification and score rubric. Text-based PDFs only; no OCR. Two-column resumes may extract out of order. Max upload 10 MB, 6 pages and 450 lines. Feedback and rewritten lines may contain sensitive data even when original excerpts are disabled. Use fictional or redacted resumes during demo. Never send confidential resumes to a third-party AI service without permission.
- No hardcoded live statistics; saved activity data comes from database. Offline results are marked as simulated. Some UI styling uses CSS against Streamlit internals; rendering varies by version. Contact is an informational page, not a mail sender. Admin has an account directory and research dashboards, not a full account lifecycle console. No OAuth, email verification, password reset, MFA, or security audit; not production-ready for real public student records.
- Session lifetime is one hour of inactivity; browser refresh may log out. Login throttling is per email. New admin/reviewer accounts require trusted CLI. Use unique passwords, restrict deployment visibility until testing, and never put secret values into screenshots.

## 7. Verified and unverified

The supplied code was compiled with `compileall`. Three actual local backend unit tests passed: authentication, password hash and isolation; save/retrieve/update/delete; PDF extraction with a generated sample PDF; simulated chatbot and resume analyzer; independent reviewer access; manual evaluation persistence and demo exclusion. Run `python -m unittest discover -s tests -v` to repeat.

The environment used to prepare this upgrade did not have Streamlit or the Gemini SDK installed and did not have a PostgreSQL service. No browser UI run, live Gemini call, cloud database connection/import, or deployment was performed. Run the full test checklist on your own machine before pushing/deploying. Additional tools are implemented but their interactive UI and live model calls remain untested. Do not present the supplied test results as academic AI-vs-Human research findings.
