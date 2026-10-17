"""商品三塔版本化导出、隔离服务与可回滚发布。仅在各阶段验收后显式调用 promote。"""
import argparse,hashlib,json,os,shutil,subprocess,sys,time,urllib.request
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v9_training')
V7=Path('/mnt/data/luo/remote_runs/product_v7_expansion')
V4=Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4')
PYTHON='/home/luo/RS_agent_remote/.venv/bin/python'
MODEL='product_three_tower_v9_expanded'
COLLECTION='rs_agent_product_three_tower_v9_20261011'
LIVE='rs-e2e-857e8b14-recommend-fast'
CANDIDATE='rs-product-v9-candidate'
BACKUP=LIVE+'-before-product-v9'

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4194304),b''):h.update(b)
    return h.hexdigest()

def write(name,value):
    p=ROOT/name;p.write_text(json.dumps(value,ensure_ascii=False,indent=2))

def wait_health(port,host='127.0.0.1',path='/actuator/health/readiness'):
    for _ in range(60):
        try:
            with urllib.request.urlopen(f'http://{host}:{port}{path}',timeout=2) as f:value=json.load(f)
            if value['status']=='UP':return value
        except Exception:pass
        time.sleep(1)
    raise RuntimeError(f'health failed: {host}:{port}')

def package():
    import torch
    selection=json.loads((ROOT/'selection.json').read_text())
    assert json.loads((ROOT/'results.json').read_text())['state']=='COMPLETE'
    state=torch.load(selection['checkpoint'],map_location='cpu',weights_only=True)
    reference=torch.load(V7/'export_candidate_v6/model.pt',map_location='cpu',weights_only=True)
    assert all(torch.equal(v,reference['model'][k]) for k,v in state['model'].items() if k.startswith('item.'))
    output=ROOT/'export';output.mkdir(exist_ok=False)
    torch.save({'model':state['model'],'config':{**state['config'],'hidden':256,'id_dim':0,'history_half_life_days':0}},output/'model.pt')
    for name in ['item_vectors.npy','item_ids.jsonl','model_definition.py']:
        os.link(V7/'export_candidate_v6'/name,output/name)
    manifest={'status':'EXPORTED_AWAITING_SERVING_VERIFICATION','dimension':1024,'candidate_count':763080,
        'model_key':MODEL,'selection':selection['selected'],'source_checkpoint':selection['checkpoint'],
        'query_task_trained':True,'item_weights_unchanged':True,
        'output_hashes':{n:digest(output/n) for n in ['model.pt','item_vectors.npy','item_ids.jsonl','model_definition.py']}}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    subprocess.run([PYTHON,str(V7/'scripts/verify_product_v6_runtime.py'),'--data',str(V4/'data'),'--evaluation',str(V7/'data/full_history_replay.jsonl'),'--export',str(output),'--runtime-directory',str(ROOT/'scripts')],check=True)

def candidate():
    index=json.loads((ROOT/'index_manifest.json').read_text())
    manifest=json.loads((ROOT/'export/manifest.json').read_text())
    assert index['count']==763080 and index['collection']==COLLECTION
    assert index['item_vector_sha256']==manifest['output_hashes']['item_vectors.npy']
    assert json.loads((ROOT/'export/runtime_replay.json').read_text())['status']=='PASS_OFFLINE_RUNTIME_REPLAY'
    unit=Path.home()/'.config/systemd/user/rs-product-v9-runtime.service'
    unit.write_text('[Unit]\nDescription=Product three tower v9 CPU runtime\nAfter=network.target\n[Service]\nEnvironment=OPENBLAS_NUM_THREADS=1\nEnvironment=OMP_NUM_THREADS=1\n'+
        f'ExecStart={PYTHON} {ROOT}/scripts/product_residual_runtime.py --directory {ROOT}/export --model-key {MODEL} --host 172.21.0.1 --port 18124\n'+
        'Restart=on-failure\nRestartSec=5\nMemoryMax=3G\nNoNewPrivileges=true\n[Install]\nWantedBy=default.target\n')
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','start','rs-product-v9-runtime.service'],check=True)
    runtime=wait_health(18124,'172.21.0.1','/health');assert runtime['model_key']==MODEL
    snapshot=json.loads(subprocess.check_output(['docker','inspect',LIVE]))[0]
    private=ROOT/'deployment';private.mkdir(exist_ok=True)
    os.chmod(private,0o700)
    p=private/'original.private.json';p.write_text(json.dumps(snapshot));p.chmod(0o600)
    launch(snapshot,CANDIDATE,18234)
    wait_health(18234)
    write('candidate_status.json',{'state':'READY_FOR_REPLAY','model_key':MODEL,'collection':COLLECTION,'port':18234,'runtime':runtime,'online_modified':False})

def launch(snapshot,name,port):
    env=dict(e.split('=',1) for e in snapshot['Config']['Env'])
    env.update(SERVER_PORT=str(port),RS_RECOMMEND_TWO_TOWER_BASE_URL='http://172.21.0.1:18124',
        RS_RECOMMEND_TWO_TOWER_MODEL_KEY=MODEL,RS_RECOMMEND_TWO_TOWER_COLLECTION=COLLECTION,
        RS_RECOMMEND_TWO_TOWER_DIMENSION='1024',RS_RECOMMEND_TWO_TOWER_ENABLED='true',
        RS_RECOMMEND_QUERY_TOWER_ENABLED='true',RS_RECOMMEND_TWO_TOWER_PRIMARY_SHARE='0.65')
    env['RS_RECOMMEND_VECTOR_SEARCH_EF']='1024'
    p=ROOT/'deployment'/(name+'.private.env');p.write_text('\n'.join(k+'='+v for k,v in env.items()));p.chmod(0o600)
    cmd=['docker','run','-d','--name',name,'--network','host','--restart','unless-stopped','--env-file',str(p)]
    for bind in snapshot['HostConfig']['Binds']:
        if ':/app/service.jar:' in bind:bind=str(ROOT/'rs-service-recommend.jar')+':/app/service.jar:ro'
        cmd.extend(['-v',bind])
    cmd.extend([snapshot['Image']]+snapshot['Config']['Cmd'])
    subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL)

def rollback():
    # 只操作本次明确命名的推荐容器；旧模型运行时和旧集合始终保留。
    names=subprocess.check_output(['docker','ps','-a','--format','{{.Names}}'],text=True).splitlines()
    if BACKUP not in names:raise RuntimeError('no v9 backup container')
    if LIVE in names:
        subprocess.run(['docker','stop',LIVE],check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['docker','rename',LIVE,LIVE+'-v9-rollback-'+str(int(time.time()))],check=True)
    subprocess.run(['docker','rename',BACKUP,LIVE],check=True)
    subprocess.run(['docker','start',LIVE],check=True,stdout=subprocess.DEVNULL);wait_health(18213)
    write('deployment_status.json',{'state':'ROLLED_BACK','timestamp':time.time()})

def promote():
    gates=json.loads((ROOT/'serving_gate.json').read_text());assert gates['state']=='PASS'
    assert gates['model_sha256']==json.loads((ROOT/'export/manifest.json').read_text())['output_hashes']['model.pt']
    snapshot=json.loads((ROOT/'deployment/original.private.json').read_text())
    current=json.loads(subprocess.check_output(['docker','inspect',LIVE]))[0]
    assert current['Id']==snapshot['Id'],'live container changed since candidate creation'
    names=subprocess.check_output(['docker','ps','-a','--format','{{.Names}}'],text=True).splitlines()
    assert BACKUP not in names
    subprocess.run(['docker','stop',LIVE],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['docker','rename',LIVE,BACKUP],check=True)
    try:
        launch(snapshot,LIVE,18213);wait_health(18213)
        subprocess.run([PYTHON,str(ROOT/'scripts/replay_product_v9.py'),'--port','18288','--output','gateway_replay.json'],check=True)
        subprocess.run(['systemctl','--user','enable','rs-product-v9-runtime.service'],check=True)
        write('deployment_status.json',{'state':'DEPLOYED_VERIFIED','model_key':MODEL,'collection':COLLECTION,
            'candidate_count':763080,'primary_share':.65,'runtime_port':18124,'service_port':18213,
            'backup_container':BACKUP,'model_sha256':gates['model_sha256'],'rollback_command':f'{PYTHON} {ROOT}/scripts/serve_product_v9.py rollback','timestamp':time.time()})
    except Exception:
        rollback();raise

if __name__=='__main__':
    os.umask(0o077)
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['package','candidate','promote','rollback']);args=p.parse_args()
    globals()[args.stage]()

