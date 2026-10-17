"""冻结候选后仅做查询训练复现与导出/运行时验收；不重新选型。"""
import json,os,subprocess,time
from pathlib import Path
import run_product_v6 as c


def main():
    before=json.loads((c.ROOT/'status.json').read_text());assert before['state']=='EXPLORATION_COMPLETE'
    c.completed=before['completed'].copy()
    selection=json.loads((c.ROOT/'selection.json').read_text());checkpoint=Path(selection['checkpoint'])
    config=json.loads((checkpoint.parent/'results.json').read_text())['config']
    c.save('finalization_plan.json',{'selected_checkpoint':str(checkpoint),'selection_frozen':True,
        'query_replica_seeds':[43,44],'purpose':'只检查固定推荐模型上的查询训练随机性，不据结果重选候选，不重复调确认集',
        'runtime_verification':'离线直接调用现有Runtime类；无HTTP端口、无Milvus写入、无线上切换'})
    if config['mode']=='query':
        replicas={}
        for seed in [43,44]:
            name='query_replica_seed'+str(seed)
            result=c.launch(name,'query',Path(config['checkpoint']),['--seed',str(seed),'--steps','600','--eval-every','600','--query-lr',str(config['query_lr'])])
            replicas[str(seed)]=result['final']
        c.save('query_replicas.json',{'fixed_candidate_unchanged':str(checkpoint),'results':replicas,'limitation':'仅查询训练种子变化，推荐初始化仍为同一seed42；不能称为整套训练多种子复验'})
    c.health();c.save('status.json',{'state':'EXPORTING','completed':c.completed,'online_modified':False})
    export=c.ROOT/'export_candidate'
    command=[c.PYTHON,str(c.ROOT/'scripts/export_product_v6.py'),'--data',str(c.DATA),'--evaluation',str(c.ROOT/'evaluation_v2/rec_dev.jsonl'),'--checkpoint',str(checkpoint),'--output',str(export)]
    with (c.ROOT/'export.log').open('w') as log:subprocess.run(command,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=600)
    command=[c.PYTHON,str(c.ROOT/'scripts/verify_product_v6_runtime.py'),'--data',str(c.DATA),'--evaluation',str(c.ROOT/'evaluation_v2/rec_dev.jsonl'),'--export',str(export),'--runtime-directory','/mnt/data/luo/remote_runs/three_tower_dataset_v4']
    with (c.ROOT/'runtime_replay.log').open('w') as log:subprocess.run(command,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=600,env={**os.environ,'CUDA_VISIBLE_DEVICES':''})
    after=c.health();initial=json.loads((c.ROOT/'online_before.json').read_text());assert initial[1]['model_sha256']==after[1]['model_sha256']
    c.save('online_after.json',after)
    c.save('status.json',{'state':'CANDIDATE_READY_OFFLINE','completed':c.completed,'selected':selection['selected'],'checkpoint':str(checkpoint),'export':str(export),'online_modified':False,'updated_unix':time.time()})


if __name__=='__main__':
    try:main()
    except Exception as error:
        c.save('status.json',{'state':'FAILED','error':str(error),'completed':c.completed,'online_modified':False});raise
