"""只收集失败类型和受限配置，不收集完整业务日志或凭据。"""
import json
from pathlib import Path
import subprocess
import sys
from probe import ROOT,accounts,http

state=json.loads((ROOT/'state.json').read_text()); users=accounts()
container=json.loads(subprocess.check_output(['docker','inspect',state['agent-fast']],text=True))[0]
env=dict(item.split('=',1) for item in container['Config']['Env'])
config={key:env[key] for key in ('RS_AGENT_DIRECT_RECOMMENDATION_ENABLED','RS_AGENT_DELEGATE_RAG_AGENT_SUPPORT_PATH','RS_RECOMMEND_SERVICE_URL','RS_AGENT_OPENAI_TEMPERATURE','RS_AGENT_OPENAI_MAX_TOKENS') if key in env}
logs=subprocess.run(['docker','logs',state['agent-fast']],text=True,capture_output=True,check=True)
phase = sys.argv[1] if len(sys.argv) > 1 else 'baseline'
terms=('AsyncRequestTimeoutException','failed to write agent stream event','tool call arguments are not valid JSON','profile_user_id is required','Read timed out', 'IllegalStateException', 'JsonEOFException', 'InvalidTool', 'required structured tool call')
matches=[line for line in (logs.stdout+'\n'+logs.stderr).splitlines() if any(term in line for term in terms)]
histories=[]
for row in json.loads((ROOT/(phase+'.json')).read_text())['failures']:
    history=http('/api/agent/sessions/'+row['session_id']+'/history',token=users[0]['accessToken'])
    histories.append({'session_id':row['session_id'],'finish_reasons':[turn['finish_reason'] for turn in history['turns']]})
result={'config':config,'failure_lines':matches,'failed_sse_authoritative_history':histories}
(ROOT/(phase+'-diagnostics.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
