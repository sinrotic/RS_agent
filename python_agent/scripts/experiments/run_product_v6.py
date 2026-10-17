"""有界三塔探索：开发集选型，再在保留用户上确认；永不自动发布。"""
import json,os,subprocess,time,urllib.request
from pathlib import Path

ROOT=Path('/mnt/data/luo/remote_runs/product_three_tower_v6_20261011')
DATA=Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4/data')
V5=Path('/mnt/data/luo/remote_runs/product_recall_v5_gpu_20261011')
PYTHON='/home/luo/RS_agent_remote/.venv/bin/python'
completed=[]


def save(name,value):
    p=ROOT/name;t=p.with_suffix('.tmp');t.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)


def health():
    values=[]
    for url in ['http://127.0.0.1:18213/actuator/health/readiness','http://172.21.0.1:18120/health']:
        with urllib.request.urlopen(url,timeout=3) as response:values.append(json.load(response))
    assert all(v['status']=='UP' for v in values)
    return values


def launch(name,mode='evaluate',checkpoint=None,flags=(),cohort='rec_dev'):
    out=ROOT/name
    if (out/'results.json').exists():
        value=json.loads((out/'results.json').read_text())
        if value['state']=='COMPLETE':completed.append(name);return value
        raise RuntimeError('保留未完成目录，请先检查checkpoint再恢复：'+name)
    free=lambda:int(subprocess.check_output(['nvidia-smi','--id=2','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True))
    if free()<5500:raise RuntimeError('GPU2剩余显存不足5.5GB，未启动训练')
    health()
    save('status.json',{'state':'RUNNING','active_run':name,'completed':completed,'online_modified':False,'updated_unix':time.time()})
    cmd=[PYTHON,str(ROOT/'scripts/product_three_tower_v6.py'),'--data',str(DATA),'--evaluation',str(ROOT/'evaluation_v2'/(cohort+'.jsonl')),'--output',str(out),'--mode',mode,*flags]
    if checkpoint:cmd+=['--checkpoint',str(checkpoint)]
    with (ROOT/(name+'.log')).open('w') as log:
        child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'CUDA_VISIBLE_DEVICES':'2'})
        failures=0;started=time.time()
        while child.poll() is None:
            time.sleep(10)
            try:health();failures=0
            except Exception:failures+=1
            if failures>=3 or free()<1500 or time.time()-started>3600:
                child.terminate()
                try:child.wait(15)
                except subprocess.TimeoutExpired:child.kill();child.wait()
                raise RuntimeError('仅停止自身任务：资源/健康/运行预算保护')
        if child.returncode:raise RuntimeError(name+' failed, see log')
    value=json.loads((out/'results.json').read_text());assert value['state']=='COMPLETE';completed.append(name)
    return value


def main():
    initial_health=health();save('online_before.json',initial_health)
    save('plan.json',{'scope':'GPU2离线三塔探索；冻结BGE、保留当前候选词表；不读取官方最终测试集、不自动上线',
        'baselines':['bge','online_v4','v5_replacement','v5_shuffle','v5_mixed'],
        'base_selection':'现有训练checkpoint中，MRR至少为online_v4的95%，按开发Hit100/MRR选择',
        'query_calibration':'固定item/user，query_lr 1e-5和5e-5各600步，每200步按开发semantic Hit10选型；必须推荐rank逐用户完全不变',
        'joint':'从选定校准checkpoint起，rec-only与joint各6062推荐步，独立随机流保证同推荐样本/负例；joint每5步追加语义，权重0.1，商品参数锚定0.01',
        'candidate_gate':'开发Hit100不低于选定推荐基线0.1个百分点，MRR不低于98%；通过者按semantic Hit10、推荐Hit100、MRR选择',
        'confirmation':'方案冻结后只对最终候选、online_v4和选定推荐基线读取保留确认用户；不据确认集调参',
        'resource_policy':'GPU2允许共享，allocator20%，CPU2核，8GB内存，nice15；只终止自身任务',
        'started_unix':time.time()})
    deadline=time.time()+600
    while not (ROOT/'evaluation_v2/manifest.json').exists():
        if time.time()>deadline:raise TimeoutError('评估集准备未完成')
        time.sleep(10)
    checkpoints={'online_v4':Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4/joint_seed42/step_6000.pt'),
        'v5_replacement':V5/'replacement32_gpu_control/last.pt','v5_shuffle':V5/'shuffle32/last.pt','v5_mixed':V5/'mixed127/last.pt'}
    baselines={'bge':launch('eval_bge')}
    for name,path in checkpoints.items():baselines[name]=launch('eval_'+name,checkpoint=path)
    baseline_mrr=baselines['online_v4']['final']['rec']['mrr']
    eligible=[n for n in checkpoints if baselines[n]['final']['rec']['mrr']>=.95*baseline_mrr]
    base=max(eligible,key=lambda n:(baselines[n]['final']['rec']['hit@100'],baselines[n]['final']['rec']['mrr']))
    base_result=baselines[base]['final'];base_checkpoint=checkpoints[base]
    save('baseline_selection.json',{'selected':base,'checkpoint':str(base_checkpoint),'metrics':{n:r['final'] for n,r in baselines.items()}})
    candidates=[('retained_base',base_checkpoint,base_result)]
    for name,rate in [('query_lr1e5','0.00001'),('query_lr5e5','0.00005')]:
        r=launch(name,'query',base_checkpoint,['--query-lr',rate])
        for entry in r['checkpoints']:candidates.append((name+'_step'+str(entry['step']),ROOT/name/f"step_{entry['step']}.pt",entry['evaluation']))
    query_best=max(candidates,key=lambda x:(x[2]['semantic']['hit@10'],x[2]['semantic']['mrr']))
    save('query_selection.json',{'selected':query_best[0],'checkpoint':str(query_best[1]),'metrics':query_best[2]})
    finalists=[query_best]
    for mode in ['rec','joint']:
        name=mode+'_continuation';r=launch(name,mode,query_best[1],['--steps','6062','--eval-every','3031'])
        finalists.append((name,ROOT/name/'step_6062.pt',r['final']))
    eligible=[x for x in finalists if x[2]['rec']['hit@100']>=base_result['rec']['hit@100']-.001 and x[2]['rec']['mrr']>=.98*base_result['rec']['mrr']]
    chosen=max(eligible,key=lambda x:(x[2]['semantic']['hit@10'],x[2]['rec']['hit@100'],x[2]['rec']['mrr']))
    save('selection.json',{'state':'FROZEN_BEFORE_CONFIRMATION','selected':chosen[0],'checkpoint':str(chosen[1]),'base':base,'base_checkpoint':str(base_checkpoint),
        'development':chosen[2],'finalists':{n:r for n,_,r in finalists},'online_modified':False,'selected_unix':time.time()})
    confirmation={}
    for name,path in [('online',checkpoints['online_v4']),('base',base_checkpoint),('candidate',chosen[1])]:
        confirmation[name]=launch('confirm_'+name,checkpoint=path,cohort='rec_confirm')['final']
    from three_tower_residual import paired_interval
    save('confirmation.json',{'metrics':confirmation,'candidate_vs_online':paired_interval(confirmation['online']['rec_ranks'],confirmation['candidate']['rec_ranks']),
        'candidate_vs_base':paired_interval(confirmation['base']['rec_ranks'],confirmation['candidate']['rec_ranks']),
        'limitations':'一个训练seed；用户为未参与本轮选型的官方valid用户，并非官方最终test；语义仍复用合成开发代理，未进行独立语义确认'})
    final_health=health();assert final_health[1]['model_key']==initial_health[1]['model_key'];save('online_after.json',final_health)
    save('status.json',{'state':'EXPLORATION_COMPLETE','completed':completed,'selected':chosen[0],'checkpoint':str(chosen[1]),'online_modified':False,'updated_unix':time.time()})


if __name__=='__main__':
    try:main()
    except Exception as error:
        save('status.json',{'state':'FAILED','error':str(error),'completed':completed,'online_modified':False,'updated_unix':time.time()});raise
