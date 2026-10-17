"""准备独立Java补丁包和CPU运行时；保持现网jar、集合和进程不变。"""
import hashlib,json,shutil,subprocess,zipfile
from pathlib import Path
from pymilvus import MilvusClient
ROOT=Path('/mnt/data/luo/remote_runs/product_v9_training')
V8=Path('/mnt/data/luo/remote_runs/product_v8_training')
V4=Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4')

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(4194304),b''):h.update(b)
    return h.hexdigest()

def main():
    snapshot=json.loads(subprocess.check_output(['docker','inspect','rs-e2e-857e8b14-recommend-fast']))[0]
    source=Path(next(b.split(':')[0] for b in snapshot['HostConfig']['Binds'] if ':/app/service.jar:' in b))
    output=ROOT/'rs-service-recommend.jar';assert not output.exists()
    entry='BOOT-INF/classes/com/sinrotic/rs/recommend/service/impl/MilvusRestVectorIndexClient.class'
    payload=(ROOT/'scripts/MilvusRestVectorIndexClient.class').read_bytes()
    with zipfile.ZipFile(source) as original,zipfile.ZipFile(output,'w') as target:
        assert entry in original.namelist()
        for info in original.infolist():target.writestr(info,payload if info.filename==entry else original.read(info.filename))
    with zipfile.ZipFile(source) as a,zipfile.ZipFile(output) as b:
        assert a.namelist()==b.namelist()
        changed=[name for name in a.namelist() if a.read(name)!=b.read(name)]
        assert changed==[entry]
    runtime=(V4/'product_residual_runtime.py').read_text()
    runtime=runtime.replace("'product_residual_uniform_history_v4'","'product_residual_uniform_history_v9'")
    runtime=runtime.replace('    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()',
        '    ThreadingHTTPServer.request_queue_size = 128\n    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()')
    (ROOT/'scripts/product_residual_runtime.py').write_text(runtime)
    shutil.copy2(V4/'two_tower_runtime.py',ROOT/'scripts/two_tower_runtime.py')
    client=MilvusClient(uri='http://127.0.0.1:19530')
    alias='rs_agent_product_three_tower_v9_20261011'
    client.create_alias(collection_name='rs_agent_product_three_tower_v8_20261011',alias=alias)
    index=json.loads((V8/'index_manifest.json').read_text());index.update(collection=alias,physical_collection='rs_agent_product_three_tower_v8_20261011')
    (ROOT/'index_manifest.json').write_text(json.dumps(index,indent=2))
    (ROOT/'deployment_build.json').write_text(json.dumps({'source_jar':str(source),'source_sha256':sha(source),'jar_sha256':sha(output),'changed_entries':changed,
        'runtime_sha256':sha(ROOT/'scripts/product_residual_runtime.py'),'ef':1024,'runtime_accept_queue':128,
        'milvus_api_reference':'https://milvus.io/api-reference/restful/v2.6.x/v2/Vector%20(v2)/Search.md','online_modified':False},indent=2))
    print('PASS: one Java class patched; isolated runtime and index alias prepared',flush=True)

if __name__=='__main__':main()
