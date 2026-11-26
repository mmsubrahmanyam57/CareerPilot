import os, tempfile, unittest, sqlite3, io
from pathlib import Path
import accounts, database as db
from ai_service import AIService
from career_chatbot import CareerChatbot
from resume_analyzer import ResumeAnalyzer, extract_resume_lines
from evaluation import evaluations_dataframe, filter_real_ai
from reportlab.pdfgen import canvas

class BackendTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.old=os.environ.get('DB_PATH'); self.cloud=os.environ.pop('DATABASE_URL',None); os.environ['DB_PATH']=str(Path(self.tmp.name)/'legacy.db')
  def make(email,role): return accounts.get(accounts.create(email,role,'Examplepass123',role=role,operator=True))
  self.student=make('s@example.com','student'); self.other=make('o@example.com','student'); self.reviewer=make('r@example.com','reviewer'); self.admin=make('a@example.com','admin')
 def tearDown(self):
  if self.old is None: os.environ.pop('DB_PATH',None)
  else: os.environ['DB_PATH']=self.old
  if self.cloud is not None: os.environ['DATABASE_URL']=self.cloud
  self.tmp.cleanup()
 def test_auth_and_isolation(self):
  self.assertEqual(accounts.authenticate('S@example.com','Examplepass123'),self.student['id'])
  self.assertIsNone(accounts.authenticate('s@example.com','wrong'))
  with self.assertRaises(ValueError): accounts.create('s@example.com','Student','Examplepass123')
  with self.assertRaises(PermissionError): accounts.create('new@example.com','Admin','Examplepass123',role='admin')
  with self.assertRaises(PermissionError):
   with accounts.authorized_workspace(self.other,self.student['id']): pass
  with self.assertRaises(PermissionError):
   with accounts.authorized_workspace(self.reviewer,self.student['id']): pass
  with accounts.authorized_workspace(self.student):
   aid=accounts.activity_save(self.student,'Roadmap','Python',{'done':False}); db.save_ai_review('abc','Sample','demo','demo',50,{'line_feedback':[]})
  with accounts.authorized_workspace(self.other):
   self.assertEqual(db.counts()['resumes'],0); self.assertEqual(accounts.activities(self.other),[])
  with accounts.authorized_workspace(self.student):
   self.assertEqual(accounts.activities(self.student)[0]['id'],aid); accounts.activity_save(self.student,'Roadmap','Python',{'done':True},record_id=aid); self.assertIn('true',accounts.activities(self.student)[0]['payload']); accounts.activity_delete(self.student,aid); self.assertEqual(accounts.activities(self.student),[])
  with sqlite3.connect(Path(self.tmp.name)/'accounts.db') as c:
   self.assertNotIn('Examplepass123',c.execute('SELECT password_hash FROM users LIMIT 1').fetchone()[0])
 def test_resume_review_evaluation(self):
  buffer=io.BytesIO(); pdf=canvas.Canvas(buffer); pdf.drawString(40,800,'Skills'); pdf.drawString(40,780,'Python and SQL'); pdf.drawString(40,760,'Projects'); pdf.drawString(40,740,'Worked on a project.'); pdf.save()
  lines=extract_resume_lines(buffer.getvalue()); result=ResumeAnalyzer(AIService(demo_mode=True,api_key='')).analyze(lines); rid=result['resume_id']
  self.assertTrue(result['simulated']); self.assertTrue(0<=result['total_score']<=100)
  with accounts.authorized_workspace(self.student): db.save_ai_review(rid,'Test','demo','demo',result['total_score'],result)
  accounts.profile(self.student,'Student','','',True)
  with accounts.authorized_workspace(self.reviewer,self.student['id']):
   with self.assertRaises(PermissionError): db.get_ai_review(rid)
   db.add_human_review(rid,'Test','forged-name','Projects',4,1,None,'Vague','No detail','Add verified features')
   self.assertEqual(db.list_human_reviews(rid)[0]['reviewer'],self.reviewer['id'])
   with self.assertRaises(PermissionError): db.save_evaluation(rid,'ai','','x',{k:2 for k in db.CRITERIA_COLUMNS})
  with accounts.authorized_workspace(self.admin,self.student['id']):
   for source in ['ai','human']: db.save_evaluation(rid,source,self.reviewer['id'],'ignored',{k:2 for k in db.CRITERIA_COLUMNS},ai_mode='demo' if source=='ai' else None)
   rows=db.list_evaluations(); self.assertEqual(len(rows),2); self.assertTrue(filter_real_ai(evaluations_dataframe(rows),False).empty)
  with accounts.authorized_workspace(self.student):
   self.assertEqual(db.get_ai_review(rid)['result']['resume_id'],rid); self.assertEqual(len(db.list_human_reviews(rid)),1); db.delete_resume_data(rid); self.assertEqual(db.counts()['resumes'],0)
 def test_demo_chat(self):
  bot=CareerChatbot(AIService(demo_mode=True,api_key='')); session=bot.new_session(); bot.start(session)
  for ans in ['BTech CSE','Python','SQL','8 CGPA','Project','Data analyst','India'][:bot.total_questions()]: bot.reply(session,ans)
  rec=bot.recommend(session); self.assertTrue(rec['simulated']); self.assertEqual(len(rec['careers']),3)

if __name__=='__main__': unittest.main()
