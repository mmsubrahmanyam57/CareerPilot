"""Database connections; local SQLite or PostgreSQL (isolated schemas)."""
import os, re, sqlite3
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from sqlalchemy import create_engine, text

workspace = ContextVar('workspace', default=None)

def cloud_url():
    url=os.getenv('DATABASE_URL','').strip()
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    if os.getenv('APP_ENV','').lower()=='production' and not url: raise ValueError('Production requires DATABASE_URL')
    if url and not url.startswith('postgresql+psycopg://'): raise ValueError('DATABASE_URL must be PostgreSQL')
    return url

@lru_cache(maxsize=4)
def engine(url): return create_engine(url, pool_pre_ping=True, hide_parameters=True)

class Row(dict):
    def __getitem__(self,k): return list(self.values())[k] if isinstance(k,int) else super().__getitem__(k)
class Result:
    def __init__(self,r, inserted=False):
        self.r=r; self.lastrowid=None
        if inserted: self.lastrowid=r.scalar_one()
    def fetchone(self):
        r=self.r.mappings().first(); return Row(r) if r is not None else None
    def fetchall(self): return [Row(r) for r in self.r.mappings().all()]
    def __iter__(self): return iter(self.fetchall())
class PGConnection:
    def __init__(self,c): self.c=c
    def execute(self,sql,params=()):
        pieces=sql.split('?'); sql=''.join(p+(f':p{i}' if i<len(pieces)-1 else '') for i,p in enumerate(pieces))
        inserted=bool(re.match(r'\s*INSERT INTO human_reviews\b',sql,re.I))
        if inserted: sql+=' RETURNING id'
        return Result(self.c.execute(text(sql),{f'p{i}':v for i,v in enumerate(params)}),inserted)
    def executescript(self,sql):
        sql=sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT','BIGSERIAL PRIMARY KEY')
        # Original DDL contains line comments; remove them before splitting.
        sql=re.sub(r'--[^\n]*','',sql)
        for statement in sql.split(';'):
            if statement.strip(): self.execute(statement)

@contextmanager
def connect(scope, schema_sql):
    if not re.fullmatch(r'(accounts|legacy|u_[a-f0-9]{32})',scope): raise ValueError('Invalid workspace')
    url=cloud_url()
    if url:
        schema='cp_'+scope
        with engine(url).begin() as c:
            c.execute(text('SELECT pg_advisory_xact_lock(hashtext(:name))'),{'name':schema})
            c.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS {schema}')
            c.exec_driver_sql(f'SET LOCAL search_path TO {schema}')
            conn=PGConnection(c); conn.executescript(schema_sql); yield conn
    else:
        base=Path(os.getenv('DB_PATH','data/career_app.db')).resolve()
        path=base if scope=='legacy' else base.parent / (scope+'.db')
        path.parent.mkdir(parents=True,exist_ok=True)
        conn=sqlite3.connect(path,timeout=20); conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            conn.executescript(schema_sql); yield conn; conn.commit()
        except Exception: conn.rollback(); raise
        finally: conn.close()
