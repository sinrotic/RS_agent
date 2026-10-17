"""保留CPU已完成结果，GPU2串行完成其余组并补同设备控制组。"""
import json,os,time
import run_product_v5_comparison as c
ROOT=c.ROOT
if __name__=='__main__':
 try:
  c.health()
  c.save('gpu_execution_manifest.json',{'device':'physical GPU2','shared_gpu_authorized':c.ALLOW_SHARED_GPU,'cuda_allocator_fraction':.20,'cpu_quota':'200%','memory_max':'8G','online_mutations':False,'source_cpu_results_preserved':True,'started_unix':time.time()})
  c.launch('v4_reference',['--evaluate-only','--initial-checkpoint','/mnt/data/luo/remote_runs/three_tower_dataset_v4/rec_seed42/step_6000.pt'])
  c.launch('replacement32',['--sampler','replacement'])
  c.launch('retained_control_gpu_eval',['--evaluate-only','--initial-checkpoint',str(ROOT/'replacement32/last.pt')])
  a=json.loads((ROOT/'replacement32/results.json').read_text())['epochs'][-1]['evaluation']
  b=json.loads((ROOT/'retained_control_gpu_eval/results.json').read_text())['evaluation']
  c.save('cpu_gpu_evaluation_parity.json',{'cpu_metrics':a['metrics'],'gpu_metrics':b['metrics'],'rank_difference_count':sum(x!=y for x,y in zip(a['ranks'],b['ranks']))})
  if abs(a['metrics']['hit@100']-b['metrics']['hit@100'])>.001:raise RuntimeError('CPU/GPU evaluation drift requires inspection')
  for name,flags in c.ARMS[1:]:c.launch(name,flags)
  # 保存CPU成果，另加同设备控制以排除训练数值差异，避免将混合后端称为严格消融。
  c.launch('replacement32_gpu_control',['--sampler','replacement'])
  c.save('status.json',{'state':'SCREENING_COMPLETE','completed':c.completed,'device':'cuda:physical2','online_modified':False,'control_for_attribution':'replacement32_gpu_control','updated_unix':time.time()})
 except Exception as error:
  c.save('status.json',{'state':'FAILED','completed':c.completed,'error':str(error),'online_modified':False,'updated_unix':time.time()});raise
