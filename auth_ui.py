import time
import streamlit as st
import accounts

STYLE='''<style>
.block-container{max-width:1260px;padding-top:2rem} .hero{background:linear-gradient(115deg,#101b39,#4038aa 58%,#167f99)!important;border-radius:24px!important;padding:2.5rem!important}
[data-testid=stSidebar]{border-right:1px solid #cbd5e140} [data-testid=stVerticalBlockBorderWrapper]{border-radius:18px!important}
.stButton button,.stDownloadButton button{border-radius:12px;font-weight:600;transition:transform .16s ease,box-shadow .16s ease}
.stButton button:hover{transform:translateY(-2px);box-shadow:0 5px 12px #635bff22}
[data-testid=stChatMessage]{border-radius:18px;border:1px solid #64748b22;padding:1rem}
.card{transition:transform .2s ease}.card:hover{transform:translateY(-3px)}
</style>'''
DARK='''<style>.stApp,[data-testid=stHeader]{background:#0d1729;color:#e2e8f0} [data-testid=stSidebar]{background:#15223a;color:#e2e8f0} .stApp h1,.stApp h2,.stApp h3,.stApp label,.stApp p,.stApp [data-testid=stMetricLabel],.stApp [data-testid=stMetricValue]{color:#e2e8f0} .card,div[data-testid=stMetric]{background:#1d2b44;border-color:#334155;color:#e2e8f0} .card h4,.card p{color:#e2e8f0} .stApp input,.stApp textarea{background:#21304b;color:#fff} </style>'''

def signout():
 for key in list(st.session_state.keys()): del st.session_state[key]
 st.rerun()

def login_gate():
 uid=st.session_state.get('auth_uid')
 if uid:
  if time.time()-st.session_state.get('auth_seen',0)>3600: signout()
  user=accounts.get(uid)
  if user:
   st.session_state.auth_seen=time.time(); return user
  signout()
 st.markdown(STYLE,unsafe_allow_html=True)
 st.markdown('<div class="hero"><h1>CareerPilot <span style="color:#a5f3fc">AI</span></h1><p>Find your direction. Build your skills. Make your next move.</p></div>',unsafe_allow_html=True)
 home,about,login,register=st.tabs(['Home','About & contact','Sign in','Create account'])
 with home:
  st.header('Your career journey starts here')
  for col,(title,desc) in zip(st.columns(3),[('Discover','Personalized career guidance and roadmaps'),('Improve','Verified resume feedback and job matching'),('Prepare','Interview practice and learning progress')]):
   with col, st.container(border=True): st.subheader(title); st.write(desc)
  st.info('Use Sign in or Create account above to open your private dashboard.')
 with about:
  st.header('About CareerPilot'); st.write('Academic prototype for career guidance, resume feedback and independent AI versus human specificity evaluation. Contact your project administrator for support or reviewer access.')
 with login:
  with st.form('login'):
   email=st.text_input('Email address',max_chars=254); pw=st.text_input('Password',type='password',max_chars=128); go=st.form_submit_button('Sign in',type='primary')
  if go:
   uid=accounts.authenticate(email,pw)
   if uid:
    for key in list(st.session_state.keys()): del st.session_state[key]
    st.session_state.auth_uid=uid; st.session_state.auth_seen=time.time(); st.rerun()
   else: st.error('Invalid credentials or temporarily locked after repeated failed attempts.')
 with register:
  with st.form('register'):
   name=st.text_input('Full name',max_chars=100); email=st.text_input('Email',max_chars=254); edu=st.text_input('Education',max_chars=200); spec=st.text_input('Specialization',max_chars=200); pw=st.text_input('Password (at least 10 characters)',type='password',max_chars=128); repeat=st.text_input('Confirm password',type='password',max_chars=128); go=st.form_submit_button('Create student account',type='primary')
  if go:
   try:
    if pw!=repeat: raise ValueError('Passwords do not match')
    accounts.create(email,name,pw,edu,spec); st.success('Account created. Open Sign in to log in.')
   except ValueError as e: st.error(str(e))
   except Exception: st.error('Registration could not be completed. Check database configuration or use another email.')
 return None
