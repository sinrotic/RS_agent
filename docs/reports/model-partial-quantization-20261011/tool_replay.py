"""冻结真实规划请求，配对验证 schema、结束状态及 RAG 查询参数。"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request
from jsonschema import Draft202012Validator

ROOT = Path('/tmp/rs-agent-partial-quantization-20261011')

def private_write(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)

def dataset():
    path = ROOT / 'planning-dataset.private.json'
    if path.exists():
        return json.loads(path.read_text())
    records = [json.loads(p.read_text()) for p in sorted((ROOT / 'capture').glob('control-*.private.json'))]
    eligible = [record for record in records if record.get('upstream_status') == 200 and
                0 < record['payload'].get('max_tokens', 0) <= 1200 and record.get('tool_calls') and
                not any(call['name'] == 'emit_final_answer' for call in record['tool_calls'])]
    eligible.sort(key=lambda record: not any(call['name'] in ['rag_support', 'call_agent'] for call in record['tool_calls']))
    chosen, hashes = [], set()
    for record in eligible:
        payload = copy.deepcopy(record['payload'])
        payload['stream'] = False
        payload.pop('stream_options', None)
        assert 0 <= payload.get('temperature', 0) <= 1
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if digest in hashes:
            continue
        hashes.add(digest)
        chosen.append({'payload': payload, 'input_sha256': digest})
        if len(chosen) == 8:
            break
    assert len(chosen) >= 4
    private_write(path, chosen)
    return chosen

def run(label, port):
    records = dataset()
    public, private = [], []
    for number, record in enumerate(records):
        schemas = {tool['function']['name']: tool['function']['parameters'] for tool in record['payload']['tools']}
        for repeat in range(2):
            payload = copy.deepcopy(record['payload'])
            payload['seed'] = repeat
            started = time.perf_counter()
            request = urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat/completions',
                data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=90) as response:
                body = json.load(response)
            choice = body['choices'][0]
            calls = choice['message'].get('tool_calls', [])
            schema_errors = 0
            missing_query = 0
            for call in calls:
                name = call['function']['name']
                try:
                    arguments = json.loads(call['function']['arguments'])
                    Draft202012Validator(schemas[name]).validate(arguments)
                    if name == 'rag_support' or (name == 'call_agent' and arguments.get('agent_name') == 'rag_agent'):
                        value = arguments.get('query') or arguments.get('task')
                        if not isinstance(value, str) or not value.strip():
                            missing_query += 1
                except Exception:
                    schema_errors += 1
            valid_end = choice['finish_reason'] in ['stop', 'tool_calls']
            public.append({'case': number, 'repeat': repeat, 'input_sha256': record['input_sha256'],
                'sampling_seed': repeat, 'temperature': payload.get('temperature'),
                'finish_reason': choice['finish_reason'],
                'tool_names': [call['function']['name'] for call in calls], 'schema_errors': schema_errors,
                'rag_missing_query': missing_query, 'complete': valid_end and bool(calls),
                'completion_tokens': body['usage']['completion_tokens'],
                'elapsed_ms': round((time.perf_counter() - started) * 1000, 2)})
            private.append({'case': number, 'repeat': repeat, 'tool_calls': calls})
    result = {'label': label, 'scope': '固定真实模型规划输入；不等同完整业务语义正确', 'samples': len(public),
              'schema_errors': sum(row['schema_errors'] for row in public),
              'rag_missing_query': sum(row['rag_missing_query'] for row in public),
              'incomplete_generations': sum(not row['complete'] for row in public), 'results': public}
    (ROOT / (label + '-planning.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    private_write(ROOT / (label + '-planning.private.json'), private)
    print('固定规划对照', label, 'samples=', len(public), 'schema_errors=', result['schema_errors'],
          'rag_missing_query=', result['rag_missing_query'], 'incomplete=', result['incomplete_generations'], flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--port', type=int, choices=[18082, 18092], required=True)
    args = parser.parse_args()
    run(args.label, args.port)
