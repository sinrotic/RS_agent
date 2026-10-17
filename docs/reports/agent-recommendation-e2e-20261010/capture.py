"""保存无凭据的环境证据与性能日志。"""
import hashlib
import json
import subprocess
from pathlib import Path

root=Path('/tmp/rs-agent-e2e-20261010-1247'); state=json.loads((root/'state.json').read_text())
metadata={'state':state,'artifacts':{},'configuration':{},'model':{
    'llm':'Qwen3.5-4B BF16','gpu':1,'max_model_len_test':16384,'gpu_utilization_test':0.78,
    'original_max_model_len':4096,'original_gpu_utilization':0.85,
    'bge_dtype':'float16','bge_batch':64,'bge_gpu_memory_fraction':0.11}}
keys={'SERVER_PORT','JAVA_OPTS','RS_AGENT_SESSION_PERSISTENCE_ENABLED','RS_AGENT_SESSION_LIFECYCLE_ENABLED',
      'RS_AGENT_SESSION_STORE_TYPE','RS_AGENT_RECOMMENDATION_TYPE','RS_AGENT_DIRECT_RECOMMENDATION_ENABLED',
      'RS_AGENT_CATALOG_CURRENCY','RS_RECOMMEND_INFERENCE_CACHE_EMBEDDING_VERSION',
      'RS_RECOMMEND_INFERENCE_CACHE_RERANKER_VERSION','RS_RECOMMEND_TRAINED_RANKING_ENABLED',
      'RS_AGENT_TRACE_ENABLED','RS_GATEWAY_MAX_REQUESTS_PER_MINUTE','RS_RECOMMEND_MULTI_RECALL_ENABLED'}
for label in ['agent-fast','agent-base','recommend-fast','recommend-base','gateway']:
    name=state[label]
    obj=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
    env=dict(v.split('=',1) for v in obj['Config']['Env'])
    metadata['configuration'][label]={k:env[k] for k in sorted(keys) if k in env}
    log=subprocess.run(['docker','logs',name],capture_output=True,text=True,check=True)
    selected=[line for line in (log.stdout+'\n'+log.stderr).splitlines()
              if '推荐轮次耗时' in line or '推荐阶段耗时' in line or 'AsyncRequestTimeoutException' in line]
    (root/(label+'-timings.log')).write_text('\n'.join(selected)+'\n')
for file in root.glob('*.jar'):
    digest=hashlib.sha256()
    with file.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''): digest.update(chunk)
    metadata['artifacts'][file.name]=digest.hexdigest()
metadata['gpu_status']=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.used,utilization.gpu',
                                                '--format=csv,noheader'],text=True).strip()
(root/'environment-evidence.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
print('saved environment and timing evidence')
