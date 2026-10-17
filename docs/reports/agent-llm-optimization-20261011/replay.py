"""按同一输入和固定温度对照最终 schema 的空字段开销，不记录回答内容。"""
import copy
import http.client
import json
from pathlib import Path
import time

ROOT=Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
calls=[json.loads(line) for line in (ROOT/'model-wire.jsonl').read_text().splitlines()]
selected=[call for call in calls if call['phase']=='baseline' and call['tool_names']==['emit_final_answer'] and call.get('usage',{}).get('completion_tokens',0)<1200][:2]
assert len(selected)==2
result=[]
for call in selected:
    original=json.loads((ROOT/'private-replay'/(call['call_id']+'.json')).read_text())
    for variant in ('before','optional-null-fields'):
        request=copy.deepcopy(original);request['temperature']=0;request['max_tokens']=4096
        if variant=='optional-null-fields':
            for tool in request['tools']:
                if tool['function']['name']=='emit_final_answer':
                    block=tool['function']['parameters']['properties']['blocks']['items']
                    block['required']=['type']
        begin=time.perf_counter(); metadata={'call_id':call['call_id'],'variant':variant,'content_chars':0,'reasoning_chars':0,'tool_argument_chars':0,'finish_reasons':[]}
        connection=http.client.HTTPConnection('127.0.0.1',18082,timeout=180)
        connection.request('POST','/v1/chat/completions',body=json.dumps(request,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
        response=connection.getresponse();assert response.status==200
        while line:=response.readline():
            if not line.startswith(b'data: ') or line.strip()==b'data: [DONE]':continue
            chunk=json.loads(line[6:])
            if chunk.get('usage'): metadata['usage']=chunk['usage']
            for choice in chunk.get('choices',[]):
                delta=choice.get('delta',{});metadata['content_chars']+=len(delta.get('content') or '')
                metadata['reasoning_chars']+=len(delta.get('reasoning_content') or '')
                for tool in delta.get('tool_calls',[]): metadata['tool_argument_chars']+=len(tool.get('function',{}).get('arguments') or '')
                if choice.get('finish_reason'):metadata['finish_reasons'].append(choice['finish_reason'])
                if delta.get('content') or delta.get('tool_calls'):metadata.setdefault('first_delta_ms',(time.perf_counter()-begin)*1000)
        metadata['ms']=(time.perf_counter()-begin)*1000;connection.close();result.append(metadata)
        (ROOT/'schema-replay.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(metadata),flush=True)
