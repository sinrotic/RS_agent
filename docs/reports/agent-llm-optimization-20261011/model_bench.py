"""固定同一真实最终请求、贪心生成，对照解码速度和完整参数。"""
import hashlib
import json
import statistics
import sys
import time
import urllib.request
from probe import ROOT

name=sys.argv[1]
wire=[json.loads(line) for line in (ROOT/'model-wire.jsonl').read_text().splitlines()]
selected=[call for call in wire if call['phase']=='typed' and call['tool_names']==['emit_final_answer']
          and isinstance(call.get('tool_choice'),dict)]
assert len(selected)>=2
selected=[selected[1], selected[-1]]
results=[]
for call in selected:
    original=json.loads((ROOT/'private-replay'/(call['call_id']+'.json')).read_text())
    original.update(stream=False,temperature=0); original.pop('stream_options',None)
    for repeat in range(4):
        begin=time.perf_counter()
        with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:18082/v1/chat/completions',
            data=json.dumps(original).encode(),headers={'Content-Type':'application/json'}),timeout=120) as response:
            body=json.load(response)
        choice=body['choices'][0]
        args=choice['message']['tool_calls'][0]['function']['arguments']
        parsed=json.loads(args)
        assert choice['finish_reason'] in ('stop','tool_calls')
        assert parsed.get('blocks')
        for block in parsed['blocks']:
            kind=block['type']
            if kind in ('text','followup_question'): assert isinstance(block.get('content'),str) and block['content'].strip()
            elif kind=='product_cards': assert block.get('card_set_id') or isinstance(block.get('item_ids'),list)
            elif kind=='comparison_table': assert block.get('content') or isinstance(block.get('item_ids'),list)
        row={'call_id':call['call_id'],'repeat':repeat,'elapsed_ms':(time.perf_counter()-begin)*1000,
             'usage':body['usage'], 'finish_reason':choice['finish_reason'],
             'argument_sha256':hashlib.sha256(json.dumps(parsed,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
        results.append(row)
        (ROOT/(name+'.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2))
        print(call['call_id'][:8],repeat,round(row['elapsed_ms'],2),row['usage']['completion_tokens'],flush=True)
