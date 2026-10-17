"""完整筛选后做配对分析和有界多种子确认；始终CPU隔离，不发布模型。"""
import importlib.util,json,os,subprocess,time
from pathlib import Path
import numpy as np
ROOT=Path('/mnt/data/luo/remote_runs/product_recall_v5_20261011')
ARMS=['replacement32','shuffle32','shuffle127','mixed127','attention_mixed127']

def save(name,value):
 p=ROOT/name;t=p.with_suffix('.tmp');t.write_text(json.dumps(value,ensure_ascii=False,indent=2));t.replace(p)

def final_result(name):
 x=json.loads((ROOT/name/'results.json').read_text())
 assert x['state']=='COMPLETE' and x['epochs'][-1]['epoch']==3
 return x['epochs'][-1]['evaluation']

def paired(a,b):
 a=np.asarray(a);b=np.asarray(b);delta=((b>0)&(b<=100)).astype(float)-((a>0)&(a<=100)).astype(float)
 rng=np.random.default_rng(20261011);boot=[rng.choice(delta,len(delta),replace=True).mean() for _ in range(2000)]
 return {'hit100_delta':float(delta.mean()),'paired_user_95pct':np.quantile(boot,[.025,.975]).tolist(),'note':'development, one fixed seed, unadjusted for multiple comparisons; no promotion claim'}

def main():
 if os.environ.get('CUDA_VISIBLE_DEVICES')!='':raise RuntimeError('CPU-only followup')
 save('followup_status.json',{'state':'WAITING_FOR_SCREENING','online_modified':False})
 deadline=time.monotonic()+12*3600
 while True:
  status=json.loads((ROOT/'status.json').read_text())
  if status['state']=='FAILED':raise RuntimeError('screening failed; no followup training launched')
  if status['state']=='SCREENING_COMPLETE':
   active=subprocess.run(['systemctl','--user','is-active','--quiet','rs-product-v5-cpu-resumed.service']).returncode==0
   if not active:break
  if time.monotonic()>deadline:raise TimeoutError('screening deadline')
  time.sleep(30)
 results={name:final_result(name) for name in ARMS}
 effects={}
 for label,a,b in [('full_traversal','replacement32','shuffle32'),('negative_count','shuffle32','shuffle127'),('negative_mix','shuffle127','mixed127'),('user_attention','mixed127','attention_mixed127')]:
  effects[label]={'control':a,'treatment':b,**paired(results[a]['ranks'],results[b]['ranks']),
                 'mrr_delta':results[b]['metrics']['mrr']-results[a]['metrics']['mrr'],
                 'ndcg_delta':results[b]['metrics']['ndcg@100']-results[a]['metrics']['ndcg@100']}
 baseline=results['shuffle32']['metrics']
 candidates=[name for name in ARMS[2:] if results[name]['metrics']['hit@100']>baseline['hit@100'] and results[name]['metrics']['mrr']>=.95*baseline['mrr'] and results[name]['metrics']['ndcg@100']>=.95*baseline['ndcg@100']]
 selected=['replacement32','shuffle32']
 if candidates:selected.append(max(candidates,key=lambda n:(results[n]['metrics']['hit@100'],results[n]['metrics']['ndcg@100'])))
 plan={'state':'SEED_CONFIRMATION','effects':effects,'selected':selected,'seeds':[43,44],
       'selection_rule':'confirm sampling controls regardless; add at most one negative/user variant only if Hit100 improves and MRR/nDCG declines <=5%; thresholds are engineering screening choices, not statistical significance',
       'limits':'same development cohort, no official test or deployment; at most six additional three-epoch runs'}
 save('adjustment_plan.json',plan);save('followup_status.json',{'state':'CONFIRMING_SEEDS','selected':selected,'online_modified':False})
 spec=importlib.util.spec_from_file_location('controller',ROOT/'scripts/experiments/run_product_v5_comparison.py');controller=importlib.util.module_from_spec(spec);spec.loader.exec_module(controller)
 controller.completed=['v4_reference']+ARMS.copy();flags=dict(controller.ARMS)
 for name in selected:
  for seed in [43,44]:controller.launch(name+'_seed'+str(seed),flags[name]+['--seed',str(seed)])
 means={}
 for name in selected:
  values=[results[name]]+[final_result(name+'_seed'+str(seed)) for seed in [43,44]]
  means[name]={key:float(np.mean([v['metrics'][key] for v in values])) for key in ['hit@10','hit@50','hit@100','mrr','ndcg@100']}
 save('seed_confirmation.json',{'seeds':[42,43,44],'means':means,'scope':'development confirmation only; online unchanged'})
 save('status.json',{'state':'CONFIRMATION_COMPLETE','completed':controller.completed,'online_modified':False})
 save('followup_status.json',{'state':'COMPLETE','online_modified':False})

if __name__=='__main__':
 try:main()
 except Exception as error:
  save('followup_status.json',{'state':'FAILED','error':str(error),'online_modified':False});raise
