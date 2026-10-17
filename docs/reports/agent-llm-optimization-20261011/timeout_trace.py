"""只读自有 QA 的内部错误摘要，不导出提示词或内部证据。"""
import json
import urllib.request
from probe import ROOT

data = {'failures':[json.loads((ROOT / 'timeout-probe.json').read_text())]}
result = []
def errors(node, path=''):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ('error', 'error_message', 'message', 'finish_reason', 'status') and isinstance(value, (str, bool)):
                yield {'path':path+'/'+key, 'value':value[:500] if isinstance(value, str) else value}
            elif key not in ('arguments', 'assistant_message', 'user_message', 'request', 'content'):
                yield from errors(value, path+'/'+key)
    elif isinstance(node, list):
        for i, value in enumerate(node): yield from errors(value, path+'/'+str(i))
for row in data['failures']:
    request = urllib.request.Request('http://127.0.0.1:18214/api/platform/agent/'+row['session_id']+'/turns',
                                    headers={'X-User-Roles':'OBSERVER'})
    with urllib.request.urlopen(request, timeout=10) as response: trace=json.load(response)
    result.append({'session_id':row['session_id'], 'errors':list(errors(trace))})
(ROOT/'timeout-failure-trace.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False, indent=2))
