"""只记录生成 token 的分类，检查短工具参数为何耗尽预算。"""
import json
import sys
import time
import urllib.request
from probe import ROOT

phase=sys.argv[1]
calls=[json.loads(line) for line in (ROOT/'model-wire.jsonl').read_text().splitlines()]
call=next(call for call in calls if call['phase']==phase and call.get('usage',{}).get('completion_tokens',0)>=1200
          and call['tool_argument_chars']<200)
request=json.loads((ROOT/'private-replay'/(call['call_id']+'.json')).read_text())
request.update(stream=False,logprobs=True,max_tokens=512);request.pop('stream_options',None)
result=[]
for repeat in range(4):
    begin=time.perf_counter()
    with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:18082/v1/chat/completions',
        data=json.dumps(request).encode(),headers={'Content-Type':'application/json'}),timeout=120) as response:body=json.load(response)
    choice=body['choices'][0];tokens=(choice.get('logprobs') or {}).get('content') or []
    flags=[]
    for token in tokens:
        value=bytes(token.get('bytes') or []).decode('utf-8',errors='replace') if token.get('bytes') else token['token']
        flags.append(value.isspace())
    max_run=run=0
    for flag in flags:
        run=run+1 if flag else 0;max_run=max(max_run,run)
    row={'call_id':call['call_id'],'repeat':repeat,'elapsed_ms':(time.perf_counter()-begin)*1000,
         'usage':body['usage'],'finish_reason':choice['finish_reason'],'tokens_observed':len(tokens),
         'whitespace_tokens':sum(flags),'max_whitespace_run':max_run,
         'tools':[{'name':tool['function']['name'],'argument_chars':len(tool['function']['arguments'])}
                  for tool in choice['message'].get('tool_calls') or []]}
    result.append(row);(ROOT/('token-probe-'+phase+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(row,ensure_ascii=False),flush=True)
