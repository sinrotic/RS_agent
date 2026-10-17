"""非流式等价请求，用于获取错误分类；不计入性能结果。"""
import json
import time
from probe import ROOT, accounts, http

users = accounts(); user = users[0]
(ROOT / 'phase.txt').write_text('blocking-diagnostic')
session = http('/api/sessions', {'entryScene':'agent-e2e'}, user['accessToken'])['sessionId']
payload = {'session_id':session, 'profile_user_id':user['profileUserId'],
           'user_message':'推荐适合编程使用的键盘，说明各自的区别', 'limit':5,
           'context':{'scene':'agent_chat', 'client_turn_id':'blocking-diagnostic', 'a2ui_state':[]}}
begin=time.perf_counter()
try:
    response=http('/api/agent/chat', payload, user['accessToken'])
    result={'complete':True, 'blocks':[block['type'] for block in response['answer_blocks']]}
except Exception as error:
    result={'complete':False, 'error':str(error)}
result['elapsed_ms']=(time.perf_counter()-begin)*1000
(ROOT/'blocking-diagnostic.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False), flush=True)
