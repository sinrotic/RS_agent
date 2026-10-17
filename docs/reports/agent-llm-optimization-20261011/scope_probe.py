"""只读取自有 QA 请求中的 RAG 结果结构，不输出原始文本或商品身份。"""
import json
from probe import ROOT

calls=[json.loads(line) for line in (ROOT/'model-wire.jsonl').read_text().splitlines()]
calls=[call for call in calls if call['phase']=='optimized-final' and call['tool_names']==['emit_final_answer']]
result=[]
def scan(node,path=''):
    if isinstance(node,dict):
        if 'item_support' in node or 'itemSupport' in node:
            yield {'path':path,'item_support_count':len(node.get('item_support',node.get('itemSupport')) or []),
                   'query_chars':len(node.get('user_query',node.get('userQuery')) or ''), 'result_keys':list(node),
                   'candidate_scoped':node.get('candidate_scoped')}
        if 'arguments' in node and isinstance(node['arguments'],dict):
            args=node['arguments']
            yield {'path':path,'argument_keys':list(args),'candidate_count':len(args.get('candidate_item_ids') or []),
                   'query_chars':len(args.get('query') or ''),'task_chars':len(args.get('task') or '')}
        for key,value in node.items():yield from scan(value,path+'/'+key)
    elif isinstance(node,list):
        for i,value in enumerate(node):yield from scan(value,path+'/'+str(i))
for call in calls:
    request=json.loads((ROOT/'private-replay'/(call['call_id']+'.json')).read_text())
    findings=[]
    for message in request['messages']:
        content=message.get('content','')
        if 'tool_results:\n' in content:
            data=json.JSONDecoder().raw_decode(content.split('tool_results:\n',1)[1])[0]
            findings.extend(scan(data))
    result.append({'call_id':call['call_id'],'rag_results':findings})
(ROOT/'rag-scope-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
