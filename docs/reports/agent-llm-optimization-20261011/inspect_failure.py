"""重放失败请求，仅公开参数结构、结束原因及 token 分类。"""
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
rows = json.loads((ROOT / 'synthesis.json').read_text())['failures']
assert len(rows) == 1
row = rows[0]
calls = [json.loads(line) for line in (ROOT / 'model-wire.jsonl').read_text().splitlines()]
calls = [call for call in calls if call['phase'] == 'synthesis' and
         row['start_epoch_ms'] <= call['epoch_ms'] <= row['start_epoch_ms'] + row['agent_done_ms']]
results = []
for call in calls[-2:]:
    request = json.loads((ROOT / 'private-replay' / (call['call_id'] + '.json')).read_text())
    request.update(stream=False, logprobs=True)
    request.pop('stream_options', None)
    begin = time.perf_counter()
    with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:18082/v1/chat/completions',
        data=json.dumps(request).encode(), headers={'Content-Type':'application/json'}), timeout=180) as response:
        body = json.load(response)
    result = {'call_id':call['call_id'], 'elapsed_ms':(time.perf_counter()-begin)*1000,
              'usage':body.get('usage'), 'choices':[]}
    for choice in body.get('choices', []):
        message = choice['message']
        classified = {'finish_reason':choice['finish_reason'], 'tools':[],
                      'content_chars':len(message.get('content') or '')}
        tokens = (choice.get('logprobs') or {}).get('content') or []
        classified['token_count'] = len(tokens)
        classified['whitespace_tokens'] = sum(1 for token in tokens if token['token'].isspace())
        for tool in message.get('tool_calls') or []:
            function = tool['function']
            item = {'name':function['name'], 'argument_chars':len(function['arguments'])}
            try:
                arguments = json.loads(function['arguments'])
                item['argument_keys'] = list(arguments)
                item['blocks'] = [{'type':block.get('type'), 'keys':list(block)} for block in arguments.get('blocks', [])]
            except json.JSONDecodeError as error:
                item['json_error'] = error.msg
                item['error_position'] = error.pos
            classified['tools'].append(item)
        result['choices'].append(classified)
    results.append(result)
    (ROOT / 'failure-replay.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False), flush=True)
