"""原服务保持到GPU2预热验证通过；按进程身份接管端口并验证核心，失败自动恢复GPU1。"""
import hashlib,json,os,signal,subprocess,time,urllib.request
from pathlib import Path
import numpy as np
ROOT=Path('/mnt/data/luo/remote_runs/bge_gpu2_migration_20261013')
PYTHON='/home/luo/RS_agent_remote/.venv/bin/python';UNIT='rs-bge-gpu2-runtime.service'
TEXTS=['办公用的静音鼠标','silent wireless mouse for office','USB-C转HDMI扩展坞','portable external SSD',
       '机械键盘','wireless bluetooth earbuds for running','办公电脑配件','移动存储设备']

def write(name,value):
    (ROOT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))

def post(port,path,data):
    start=time.monotonic();req=urllib.request.Request(f'http://127.0.0.1:{port}{path}',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as f:value=json.load(f)
    return value,(time.monotonic()-start)*1000

def probe(port):
    embedded,et=post(port,'/internal/model/embed',{'request_id':'migration-parity','model_key':'bge-m3','inputs':{'texts':TEXTS},'options':{'normalize':True,'batch_size':8}})
    ranked,rt=post(port,'/internal/model/rank',{'request_id':'migration-parity-rank','model_key':'bge-reranker-v2-m3','inputs':{'query':'办公用的静音鼠标',
        'candidates':[{'item_id':str(i),'text':t} for i,t in enumerate(TEXTS)]},'options':{'top_k':8}})
    return {'vectors':np.asarray([r['vector'] for r in embedded['vectors']]),'ranks':ranked['items'],'embedding_ms':et,'reranking_ms':rt}

def healthy(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=2) as f:return json.load(f)['status']=='UP'
    except Exception:return False

def wait(port,timeout=180):
    began=time.time()
    while not healthy(port):
        if time.time()-began>timeout:raise TimeoutError('BGE启动/端口接管超时')
        time.sleep(.25)

def identity(snapshot):
    p=Path('/proc')/str(snapshot['pid'])
    try:return p.joinpath('stat').read_text().split(') ',1)[1].split()[19]==snapshot['starttime']
    except FileNotFoundError:return False

def main():
    s=json.loads((ROOT/'private/original.json').read_text());old_pid=s['pid'];switched=False;legacy_disabled=False
    assert identity(s);assert s['original_gpu']==1 and s['target_gpu']==2
    baseline=probe(s['primary_port']);write('progress.json',{'state':'PREHEATING_GPU2','timestamp':time.time()})
    unit=Path.home()/'.config/systemd/user'/UNIT
    unit.write_text('[Unit]\nDescription=BGE embedding and reranking on GPU2\nAfter=network.target\n[Service]\n'+
        f'ExecStart={PYTHON} {ROOT}/scripts/bge_gpu2_runtime.py --mode launch\n'+
        'Restart=on-failure\nRestartSec=5\nMemoryMax=12G\nNoNewPrivileges=true\n[Install]\nWantedBy=default.target\n')
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','start',UNIT],check=True)
    try:
        wait(s['staging_port']);candidate=probe(s['staging_port'])
        error=float(np.max(abs(baseline['vectors']-candidate['vectors'])));assert error<5e-4
        assert [r['item_id'] for r in baseline['ranks']]==[r['item_id'] for r in candidate['ranks']]
        old_scores={r['item_id']:r['score'] for r in baseline['ranks']};score_error=max(abs(r['score']-old_scores[r['item_id']]) for r in candidate['ranks']);assert score_error<.01
        checks={'state':'PASS','embedding_max_error':error,'reranking_max_error':score_error,'same_ranking_order':True,
            'gpu1_embedding_ms':baseline['embedding_ms'],'gpu2_embedding_ms':candidate['embedding_ms'],
            'gpu1_reranking_ms':baseline['reranking_ms'],'gpu2_reranking_ms':candidate['reranking_ms']}
        write('parity.json',checks);print('GPU2_PREHEAT_PARITY',checks,flush=True)
        # 优先等待原端口空闲，接管使用已预热的同一个模型实例。
        deadline=time.time()+15
        while True:
            active=subprocess.check_output(['ss','-Htn','state','established','sport','=',':'+str(s['primary_port'])],text=True).strip()
            if not active:break
            if time.time()>deadline:raise RuntimeError('原BGE有持续请求，暂不打断，保留GPU1服务')
            time.sleep(.1)
        assert identity(s)
        if s['legacy_unit_enable_state']=='enabled':
            subprocess.run(['systemctl','--user','disable','rs-bge-runtime.service'],check=True);legacy_disabled=True
        (ROOT/'private/activate.request').write_text(str(time.time()))
        os.kill(old_pid,signal.SIGTERM);switched=True
        deadline=time.time()+30
        while True:
            state=json.loads((ROOT/'runtime_status.json').read_text())
            if state['state']=='LIVE_READY' and healthy(s['primary_port']):break
            if time.time()>deadline:raise TimeoutError('预热模型未完成原端口接管')
            time.sleep(.05)
        live=probe(s['primary_port']);assert float(np.max(abs(live['vectors']-baseline['vectors'])))<5e-4
        subprocess.run([PYTHON,'/mnt/data/luo/remote_runs/product_v16_final/scripts/replay_product_final.py',
            '--port','18288','--output','bge_gpu2_migration_gateway_replay.json'],check=True)
        subprocess.run(['systemctl','--user','enable',UNIT],check=True)
        pid=int(subprocess.check_output(['systemctl','--user','show',UNIT,'-p','MainPID','--value'],text=True))
        raw=(Path('/proc')/str(pid)/'environ').read_bytes().split(b'\0');env=dict(x.split(b'=',1) for x in raw if b'=' in x);assert env[b'CUDA_VISIBLE_DEVICES']==b'2'
        mapping=dict(line.strip().split(', ') for line in subprocess.check_output(['nvidia-smi','--query-gpu=index,uuid','--format=csv,noheader'],text=True).splitlines())
        processes=[line.strip().split(', ') for line in subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,used_memory','--format=csv,noheader'],text=True).splitlines()]
        own=[r for r in processes if int(r[1])==pid];assert len(own)==1 and own[0][0]==mapping['2']
        assert not identity(s)
        report={'state':'MIGRATED_VERIFIED','from_gpu':1,'to_gpu':2,'original_pid':old_pid,'new_pid':pid,'port':s['primary_port'],'unit':UNIT,
            'memory':own[0][2],'primary_interface_unchanged':True,'gateway_replay':'PASS','model_output_parity':'PASS',
            'qwen_remains_stopped':not healthy(18082),'timestamp':time.time()}
        assert report['qwen_remains_stopped'];write('deployment_status.json',report);write('progress.json',report);print('BGE_GPU_MIGRATION_COMPLETE',report,flush=True)
    except Exception as error:
        subprocess.run(['systemctl','--user','stop',UNIT],check=True)
        if switched:
            subprocess.run(['systemd-run','--user','--unit=rs-bge-gpu1-rollback','--property=Restart=on-failure',PYTHON,str(ROOT/'scripts/bge_gpu2_runtime.py'),'--mode','restore'],check=True)
            wait(s['primary_port'])
        if legacy_disabled:subprocess.run(['systemctl','--user','enable','rs-bge-runtime.service'],check=True)
        write('progress.json',{'state':'FAILED_GPU1_RETAINED_OR_RESTORED','error':repr(error),'timestamp':time.time()});raise

if __name__=='__main__':main()
