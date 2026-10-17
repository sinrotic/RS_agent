"""GPU2隔离扩库流水线，只读线上健康状态，编码可恢复，不发布。"""
import hashlib,json,os,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v7_expansion')
OLD=Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4/data')
PYTHON='/home/luo/RS_agent_remote/.venv/bin/python'


def save(name,value):
    p=ROOT/name;t=p.with_suffix('.tmp');t.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)


def health():
    result=[]
    for url in ['http://127.0.0.1:18213/actuator/health/readiness','http://172.21.0.1:18120/health']:
        with urllib.request.urlopen(url,timeout=3) as response:result.append(json.load(response))
    assert all(r['status']=='UP' for r in result)
    return result


def launch(stage,script,flags):
    free=lambda:int(subprocess.check_output(['nvidia-smi','--id=2','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True))
    if free()<5500:raise RuntimeError('GPU2剩余显存不足5.5GB')
    save('status.json',{'state':stage,'online_modified':False,'updated_unix':time.time()})
    with (ROOT/(stage.lower()+'.log')).open('a') as log:
        child=subprocess.Popen([PYTHON,str(ROOT/'scripts'/script),*flags],stdout=log,stderr=subprocess.STDOUT)
        failures=0;started=time.time()
        while child.poll() is None:
            time.sleep(10)
            try:health();failures=0
            except Exception:failures+=1
            if failures>=3 or free()<1500 or time.time()-started>7200:
                child.terminate()
                try:child.wait(15)
                except subprocess.TimeoutExpired:child.kill();child.wait()
                raise RuntimeError('停止自身子进程：健康/显存/运行预算保护；已有编码块保留')
        if child.returncode:raise RuntimeError(stage+'失败，请检查阶段日志')


def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    before=health();save('online_before.json',before)
    save('plan.json',{'models':['现网v4冻结权重','v6分阶段三塔冻结权重'],'scenarios':['旧库旧历史','扩库旧历史','扩库完整训练历史'],
        'cohorts':'保留v6开发/确认用户和顺序；已经复评过，不称全新保留集','semantic':'同347条合成开发查询；不读取官方test',
        'selection':'固定两个模型，不因本轮结果选checkpoint或调参；先测直接扩库的收益/代价',
        'candidate_policy':'只按训练期保留正反馈商品追加；不使用验证目标决定词表','resource_policy':'GPU2允许共享，allocator20%，CPU2核，8GB系统内存，nice15；只停止自身进程'})
    deadline=time.time()+900
    while not (ROOT/'data/manifest.json').exists():
        if time.time()>deadline:raise TimeoutError('扩库准备未完成')
        time.sleep(10)
    launch('ENCODING','encode_product_v7_catalog.py',['--data',str(ROOT/'data'),'--old-data',str(OLD),'--autotune'])
    launch('EVALUATING','evaluate_product_v7_catalog.py',['--root',str(ROOT)])
    after=health();assert before[1]['model_sha256']==after[1]['model_sha256'];save('online_after.json',after)
    save('status.json',{'state':'COMPLETE','online_modified':False,'updated_unix':time.time()})


if __name__=='__main__':
    try:main()
    except Exception as e:save('status.json',{'state':'FAILED','error':str(e),'online_modified':False,'updated_unix':time.time()});raise
