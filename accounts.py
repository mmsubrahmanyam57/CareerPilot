"""Account authentication and explicit reviewer sharing. No default passwords."""
import hashlib, hmac, secrets, re, uuid, json, time
from contextlib import contextmanager
from contextvars import ContextVar
from storage import connect, workspace
SCHEMA='''CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('student','reviewer','admin')),
 education TEXT NOT NULL DEFAULT '', specialization TEXT NOT NULL DEFAULT '', shared INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (email TEXT PRIMARY KEY, failures INTEGER NOT NULL, until_time REAL NOT NULL);
CREATE TABLE IF NOT EXISTS usage_limits (bucket TEXT PRIMARY KEY, used INTEGER NOT NULL);
'''
principal=ContextVar('principal',default=None)
ACTIVITY='''CREATE TABLE IF NOT EXISTS activities (id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, payload TEXT NOT NULL, mode TEXT NOT NULL, created_at TEXT NOT NULL);'''
def now():
 from datetime import datetime,timezone
 return datetime.now(timezone.utc).isoformat(timespec='seconds')
def password_hash(password):
 salt=secrets.token_hex(16); return salt+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
def verify(password,stored):
 try:
  salt,digest=stored.split(':'); return hmac.compare_digest(digest,hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex())
 except (ValueError,TypeError): return False

def create(email,name,password,education='',specialization='',role='student',*,operator=False):
 email=email.strip().lower(); name=name.strip()
 if role!='student' and not operator: raise PermissionError('Role restricted')
 if role not in ('student','reviewer','admin'): raise ValueError('Invalid role')
 if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or len(email)>254: raise ValueError('Enter a valid email')
 if not name or len(name)>100 or not 10<=len(password)<=128: raise ValueError('Name required; password must be 10–128 characters')
 with connect('accounts',SCHEMA) as c:
  if c.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone(): raise ValueError('Email already registered')
  uid=uuid.uuid4().hex
  c.execute('INSERT INTO users(id,email,name,password_hash,role,education,specialization,created_at) VALUES (?,?,?,?,?,?,?,?)',(uid,email,name,password_hash(password),role,education[:200],specialization[:200],now()))
 return uid

def get(uid):
 with connect('accounts',SCHEMA) as c:
  r=c.execute('SELECT id,email,name,role,education,specialization,shared,created_at FROM users WHERE id=?',(uid,)).fetchone()
  return dict(r) if r else None

def authenticate(email,password):
 email=email.strip().lower()[:254]
 if len(password)>128: return None
 with connect('accounts',SCHEMA) as c:
  a=c.execute('SELECT * FROM attempts WHERE email=?',(email,)).fetchone(); t=time.time()
  if a and a['until_time']>t: return None
  r=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
  # Do comparable work even for an unknown email.
  ok=verify(password,r['password_hash'] if r else '00'*16+':'+ '00'*32)
  if not r or not ok:
   n=(a['failures'] if a and a['until_time']==0 else 0)+1
   c.execute('INSERT INTO attempts(email,failures,until_time) VALUES (?,?,?) ON CONFLICT(email) DO UPDATE SET failures=excluded.failures,until_time=excluded.until_time',(email,n,t+300 if n>=5 else 0)); return None
  c.execute('DELETE FROM attempts WHERE email=?',(email,)); return r['id']

def users(actor):
 if actor['role'] not in ('admin','reviewer'): raise PermissionError('Role restricted')
 with connect('accounts',SCHEMA) as c:
  sql='SELECT id,name,role,shared,created_at FROM users'
  if actor['role']=='reviewer': sql+=" WHERE role='student' AND shared=1"
  return [dict(r) for r in c.execute(sql+' ORDER BY created_at DESC')]

def profile(actor,name,education,specialization,shared):
 if not name.strip() or len(name)>100: raise ValueError('Name required')
 with connect('accounts',SCHEMA) as c:
  c.execute('UPDATE users SET name=?,education=?,specialization=?,shared=? WHERE id=?',(name.strip(),education[:200],specialization[:200],int(bool(shared) and actor['role']=='student'),actor['id']))

@contextmanager
def authorized_workspace(actor,target=None):
 # Refresh role and sharing on every rerun; target is never accepted without authorization.
 actor=get(actor['id'])
 if not actor: raise PermissionError('Sign in again')
 if target=='legacy':
  if actor['role']!='admin': raise PermissionError('Admin only')
  scope='legacy'
 elif target and target!=actor['id']:
  owner=get(target)
  if actor['role'] not in ('reviewer','admin') or not owner or owner['role']!='student' or not owner['shared']: raise PermissionError('Student has not shared this workspace')
  scope='u_'+target
 else: scope='u_'+actor['id']
 token=workspace.set(scope); who=principal.set(actor)
 try: yield
 finally: principal.reset(who); workspace.reset(token)

def activity_save(actor,kind,title,payload,mode='local',record_id=None):
 if not principal.get() or principal.get()['id']!=actor['id'] or workspace.get()!='u_'+actor['id'] or principal.get()['role']!='student': raise PermissionError('Own student workspace required')
 rid=record_id or uuid.uuid4().hex
 with connect(workspace.get(),ACTIVITY) as c:
  c.execute('INSERT INTO activities(id,kind,title,payload,mode,created_at) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,payload=excluded.payload,mode=excluded.mode WHERE activities.kind=excluded.kind',(rid,kind,title[:120],json.dumps(payload,ensure_ascii=False),mode,now()))
 return rid

def activities(actor):
 if not principal.get() or principal.get()['id']!=actor['id'] or workspace.get()!='u_'+actor['id']: raise PermissionError('Own workspace required')
 with connect(workspace.get(),ACTIVITY) as c:
  return [dict(r) for r in c.execute('SELECT * FROM activities ORDER BY created_at DESC')]

def activity_delete(actor,rid):
 if not principal.get() or principal.get()['id']!=actor['id'] or workspace.get()!='u_'+actor['id']: raise PermissionError('Own workspace required')
 with connect(workspace.get(),ACTIVITY) as c: c.execute('DELETE FROM activities WHERE id=?',(rid,))


def consume_ai_quota(actor):
    """Daily logical request limits. Retry calls may still consume provider quota."""
    import os
    if not principal.get() or principal.get()['id']!=actor['id'] or actor['role']!='student':
        raise PermissionError('Student access required')
    day=now()[:10]
    with connect('accounts',SCHEMA) as c:
        for bucket,cap in [(day+':global',int(os.getenv('AI_DAILY_GLOBAL_LIMIT','300'))),(day+':'+actor['id'],int(os.getenv('AI_DAILY_USER_LIMIT','40')))]:
            if cap<=0: raise ValueError('Live AI request limit reached')
            r=c.execute('INSERT INTO usage_limits(bucket,used) VALUES (?,1) ON CONFLICT(bucket) DO UPDATE SET used=usage_limits.used+1 WHERE usage_limits.used < ? RETURNING used',(bucket,cap)).fetchone()
            if not r: raise ValueError('Daily live AI request limit reached. Use offline mode or contact your administrator.')
