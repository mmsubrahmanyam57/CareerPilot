"""Run locally, or from a trusted terminal connected to the cloud database."""
import argparse, getpass
from dotenv import load_dotenv
load_dotenv()
from accounts import create
p=argparse.ArgumentParser(); p.add_argument('--role',choices=['admin','reviewer','student'],required=True); p.add_argument('--email',required=True); p.add_argument('--name',required=True)
a=p.parse_args(); password=getpass.getpass('Password (10+ characters): ')
if password!=getpass.getpass('Confirm password: '): raise SystemExit('Passwords differ')
try: create(a.email,a.name,password,role=a.role,operator=True); print('Account created:',a.email,a.role)
except ValueError as e: raise SystemExit(str(e))
