"""资源限额下顺序运行 v5 消融；只读线上健康状态，不发布模型。"""
import hashlib,json,os,signal,subprocess,sys,time,urllib.request
from pathlib import Path
ROOT=Path(os.environ.get('PRODUCT_V5_ROOT','/mnt/data/luo/remote_runs/product_recall_v5_20261011'))
DEVICE=os.environ.get('PRODUCT_V5_DEVICE','cpu')
ALLOW_SHARED_GPU=os.environ.get('PRODUCT_V5_ALLOW_SHARED_GPU')=='1'
DATA=Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4/data')
PYTHON='/home/luo/RS_agent_remote/.venv/bin/python'
SCRIPT=ROOT/'scripts/experiments/product_recall_v5.py'
ARMS=[('replacement32',['--sampler','replacement']),('shuffle32',[]),
      ('shuffle127',['--negatives','127']),('mixed127',['--negatives','127','--negative-mode','mixed']),
      ('attention_mixed127',['--negatives','127','--negative-mode','mixed','--user','attention'])]

def save(name,value):
 p=ROOT/name;t=p.with_suffix('.tmp');t.write_text(json.dumps(value,ensure_ascii=False,indent=2));t.replace(p)

def health():
 for url in ['http://127.0.0.1:18213/actuator/health/readiness','http://172.21.0.1:18120/health']:
  with urllib.request.urlopen(url,timeout=3) as response:
   if json.load(response).get('status')!='UP':raise RuntimeError('online readiness not UP')

def gpu_busy(allowed_pid=None):
 if DEVICE!='cuda':return False
 if ALLOW_SHARED_GPU:
  free=int(subprocess.check_output(['nvidia-smi','--id=2','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True).strip())
  return free<(1500 if allowed_pid else 5500)
 uuid=subprocess.check_output(['nvidia-smi','--id=2','--query-gpu=uuid','--format=csv,noheader'],text=True).strip()
 apps=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid','--format=csv,noheader'],text=True)
 return any(parts[0].strip()==uuid and int(parts[1].strip())!=allowed_pid for line in apps.splitlines() if len(parts:=line.split(','))==2)

def launch(name,flags):
 existing=ROOT/name/'results.json'
 if existing.exists() and json.loads(existing.read_text()).get('state')=='COMPLETE':
  completed.append(name);summarize();return
 if gpu_busy():raise RuntimeError('GPU2 free memory is below 5500 MiB' if ALLOW_SHARED_GPU else 'GPU2 has another compute job; exclusive mode requires an idle GPU')
 save('status.json',{'state':'RUNNING','active_run':name,'completed':completed,'device':DEVICE,'online_modified':False,'updated_unix':time.time()})
 command=[PYTHON,str(SCRIPT),'--data',str(DATA),'--output',str(ROOT/name),'--epochs','3','--seed','42','--device',DEVICE]+flags
 with (ROOT/(name+'.log')).open('w') as log:
  child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'CUDA_VISIBLE_DEVICES':'2' if DEVICE=='cuda' else ''})
  failures=0;start=time.monotonic()
  while child.poll() is None:
   time.sleep(20)
   try:health();failures=0
   except Exception:failures+=1
   if failures>=3 or gpu_busy(child.pid) or time.monotonic()-start>4*3600:
    child.terminate()
    try:child.wait(timeout=15)
    except subprocess.TimeoutExpired:child.kill();child.wait()
    raise RuntimeError('stopped own training after readiness failure, GPU resource guard, or 4h run budget')
  if child.returncode:raise RuntimeError(name+' exited '+str(child.returncode))
 result=json.loads((ROOT/name/'results.json').read_text());assert result['state']=='COMPLETE'
 if not flags or '--evaluate-only' not in flags:
  if result['config']['sampler']=='shuffle':assert all(e['full_epoch'] and e['epoch_unique']==result['train_rows'] for e in result['epochs'])
 completed.append(name);summarize()

def summarize():
 results={}
 for name in completed:
  x=json.loads((ROOT/name/'results.json').read_text())
  results[name]={'seconds':x.get('seconds'),'epochs':[{'epoch':e['epoch'],'metrics':e['evaluation']['metrics'],'epoch_unique_fraction':e['epoch_unique_fraction']} for e in x['epochs']]}
  if 'evaluation' in x:results[name]['evaluation']=x['evaluation']['metrics']
 save('comparison.json',{'scope':'seed42 development screening; not independent test or production promotion','runs':results,'followup':'only choose extensions/multiple seeds after inspecting development quality and stage costs'})

completed=[]
if __name__=='__main__':
 try:
  if os.environ.get('CUDA_VISIBLE_DEVICES')!=('2' if DEVICE=='cuda' else ''):raise RuntimeError('device visibility mismatch')
  health()
  manifest={'arms':ARMS,'epochs':3,'seeds':[42],'train_rows':387951,'candidate_count':203887,'data_source':str(DATA),'script_sha256':hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),'resource_policy':{'device':DEVICE,'cpu_quota':'200%','memory_max':'8G','nice':15,'io':'idle','physical_gpu':2 if DEVICE=='cuda' else None,'shared_gpu_authorized':ALLOW_SHARED_GPU,'cuda_allocator_fraction':.20 if DEVICE=='cuda' else None},'negative_policy':'known positives excluded, unique candidate IDs; category negatives are weak, not explicit dislikes','selection':'same development cohort, official test not read; final step and curves both reported','started_unix':time.time()}
  save('experiment_manifest.json',manifest)
  launch('v4_reference',['--evaluate-only','--initial-checkpoint','/mnt/data/luo/remote_runs/three_tower_dataset_v4/rec_seed42/step_6000.pt'])
  for name,flags in ARMS:launch(name,flags)
  save('status.json',{'state':'SCREENING_COMPLETE','completed':completed,'online_modified':False,'updated_unix':time.time()})
 except Exception as error:
  save('status.json',{'state':'FAILED','completed':completed,'error':str(error),'online_modified':False,'updated_unix':time.time()});raise
