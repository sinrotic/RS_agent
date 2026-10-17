"""用原BGE配置在GPU2预热，再接管原端口；不重载模型，不改变编码或排序。"""
import argparse,hashlib,importlib.util,json,logging,os,socket,sys,threading,time
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/bge_gpu2_migration_20261013')

def write(state,**details):
    tmp=ROOT/'runtime_status.tmp';tmp.write_text(json.dumps({'state':state,'timestamp':time.time(),**details},ensure_ascii=False,indent=2));tmp.replace(ROOT/'runtime_status.json')

def main(mode):
    snapshot=json.loads((ROOT/'private/original.json').read_text())
    if mode in ['launch','restore']:
        env={**snapshot['env'],'CUDA_VISIBLE_DEVICES':'2' if mode=='launch' else '1'}
        os.chdir(snapshot['cwd'])
        argv=[snapshot['argv'][0],str(ROOT/'scripts/bge_gpu2_runtime.py'),'--mode','serve'] if mode=='launch' else [snapshot['argv'][0],snapshot['runtime_copy'],*snapshot['argv'][2:]]
        os.execvpe(argv[0],argv,env)
    assert mode=='serve' and os.environ['CUDA_VISIBLE_DEVICES']=='2'
    source=Path(snapshot['runtime_copy']);assert hashlib.sha256(source.read_bytes()).hexdigest()==snapshot['runtime_source_sha256']
    spec=importlib.util.spec_from_file_location('migration_bge_original',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sys.argv=snapshot['argv'][1:];args=module.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    runtime=module.EmbeddingRuntime(args.model_path,args.device,args.reranker_path,dtype=args.dtype,
        rerank_batch_size=args.rerank_batch_size,gpu_memory_fraction=args.gpu_memory_fraction)
    module.EmbeddingRequestHandler.runtime=runtime;stage=None
    flag=ROOT/'private/activate.request'
    if not flag.exists():
        stage=module.BgeHTTPServer((args.host,snapshot['staging_port']),module.EmbeddingRequestHandler)
        threading.Thread(target=stage.serve_forever,daemon=True).start()
        write('STAGED_READY',gpu=2,port=snapshot['staging_port'],pid=os.getpid())
        while not flag.exists():time.sleep(.1)
    deadline=time.time()+30
    while True:
        try:primary=module.BgeHTTPServer((args.host,args.port),module.EmbeddingRequestHandler);break
        except OSError as error:
            if error.errno!=98 or time.time()>deadline:raise
            time.sleep(.03)
    if stage is not None:stage.shutdown();stage.server_close()
    write('LIVE_READY',gpu=2,port=args.port,pid=os.getpid())
    primary.serve_forever()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['launch','serve','restore'],required=True)
    try:main(p.parse_args().mode)
    except Exception as e:write('FAILED',error=repr(e));raise
