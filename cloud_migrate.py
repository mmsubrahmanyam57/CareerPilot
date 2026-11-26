"""Optional one-time local SQLite -> empty PostgreSQL import. Never upload DB files to GitHub.
Use a trusted terminal with DATABASE_URL in .env or environment. Explicit --apply required.
"""
import argparse, os, re, sqlite3
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import text
from storage import cloud_url, engine, PGConnection
from accounts import SCHEMA as ACCOUNT_SCHEMA, ACTIVITY
from database import SCHEMA as REVIEW_SCHEMA

p=argparse.ArgumentParser(); p.add_argument('--apply',action='store_true'); p.add_argument('--legacy-path',default=os.getenv('DB_PATH','data/career_app.db')); a=p.parse_args()
base=Path(a.legacy_path).resolve()
scopes={}
if base.is_file(): scopes['legacy']=base
if (base.parent/'accounts.db').is_file(): scopes['accounts']=base.parent/'accounts.db'
for f in base.parent.glob('u_*.db'):
 if re.fullmatch(r'u_[a-f0-9]{32}',f.stem): scopes[f.stem]=f
if not scopes: raise SystemExit('No local databases found.')
print('Local database files found:',len(scopes))
if not a.apply: raise SystemExit('Dry run only. Use --apply after checking consent, backups and target database.')
url=cloud_url()
if not url: raise SystemExit('Set PostgreSQL DATABASE_URL in a trusted local environment.')
# Single target transaction. Fail if a destination already has records; never overwrite.
with engine(url).begin() as c:
 for scope,path in sorted(scopes.items()):
  schema='cp_'+scope
  c.execute(text('SELECT pg_advisory_xact_lock(hashtext(:name))'),{'name':schema})
  c.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS {schema}')
  c.exec_driver_sql(f'SET LOCAL search_path TO {schema}')
  ddl=ACCOUNT_SCHEMA if scope=='accounts' else REVIEW_SCHEMA+ACTIVITY
  PGConnection(c).executescript(ddl)
  tables=['users'] if scope=='accounts' else ['resumes','ai_reviews','human_reviews','evaluations','activities']
  with sqlite3.connect(path) as src:
   src.row_factory=sqlite3.Row
   for table in tables:
    if not src.execute('SELECT name FROM sqlite_master WHERE type=? AND name=?',('table',table)).fetchone(): continue
    if c.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar_one(): raise RuntimeError('Target contains records. Import requires an empty target; no overwrite performed.')
    rows=[dict(r) for r in src.execute(f'SELECT * FROM {table}')]
    if rows:
     keys=list(rows[0]); assert all(re.fullmatch(r'[a-z_]+',k) for k in keys)
     c.execute(text(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join(':'+k for k in keys)})"),rows)
    if table in ('human_reviews','evaluations') and rows:
     c.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}','id'), (SELECT MAX(id) FROM {table}))"))
print('Import committed successfully. Sign in and verify data. Old local files were not changed.')
