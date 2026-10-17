"""撤除诊断代理后，再验证真实完整推荐及直接模型连接。"""
import json
import re
import subprocess
import urllib.request
from probe import ROOT,accounts,one

state=json.loads((ROOT/'state.json').read_text())
config=json.loads(subprocess.check_output(['docker','inspect',state['agent-fast']],text=True))[0]
env=dict(entry.split('=',1) for entry in config['Config']['Env'] if '=' in entry)
assert env['RS_AGENT_OPENAI_BASE_URL']=='http://127.0.0.1:18082/v1'
assert env['RS_AGENT_DIRECT_RECOMMENDATION_ENABLED']=='false'
assert env['RS_AGENT_LLM_SYNTHESIS_ENABLED']=='true'
assert not (ROOT/'private-replay').exists() and not (ROOT/'private-model-backup').exists()
def success_count():
    with urllib.request.urlopen('http://127.0.0.1:18082/metrics',timeout=10) as response:text=response.read().decode()
    return sum(float(value) for value in re.findall(r'^vllm:request_success_total(?:\{[^}]*\})?\s+([0-9.eE+-]+)',text,re.MULTILINE))
users=accounts(); before=success_count()
row=one(users[0],'推荐鼠标','fast','post-retirement')
assert row.get('response') and not row.get('error')
assert len(row['response']['recommended_items'])==5 and len(row['catalog'])==5
assert row['history']['turns'][-1]['finish_reason']=='FINAL_ANSWER'
assert not row['response']['degradation_reasons']
delta=success_count()-before;assert delta>=1
row['model_success_counter_delta']=delta
row['direct_recommendation_disabled']=True
row['diagnostic_proxy_removed']=True
(ROOT/'post-retirement-smoke.json').write_text(json.dumps(row,ensure_ascii=False,indent=2))
print('撤除代理后的真实完整推荐通过；模型成功请求计数增量',delta,flush=True)
