"""相同固定提示词的 16 路短工具请求；不替代长上下文持续负载评估。"""
import argparse
import concurrent.futures
import copy
import json
import math
from pathlib import Path
import statistics
import threading
import time
import urllib.request

from jsonschema import Draft202012Validator

ROOT = Path('/tmp/rs-agent-partial-quantization-20261011')

def run(label):
    source = json.loads((ROOT / 'production-model.json').read_text())
    payload = copy.deepcopy(source['request_templates']['named_tool'])
    payload['stream'] = False
    payload.pop('stream_options', None)
    payload['seed'] = 0
    assert payload['temperature'] == 0
    schemas = {tool['function']['name']: tool['function']['parameters'] for tool in payload['tools']}
    lock = threading.Lock()
    active, peak = 0, 0
    def request(number):
        nonlocal active, peak
        started = time.perf_counter()
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            request = urllib.request.Request('http://127.0.0.1:18082/v1/chat/completions',
                data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=90) as response:
                body = json.load(response)
            choice = body['choices'][0]
            assert choice['finish_reason'] in ['stop', 'tool_calls']
            calls = choice['message'].get('tool_calls', [])
            assert len(calls) == 1
            for call in calls:
                name = call['function']['name']
                assert name == payload['tool_choice']['function']['name']
                Draft202012Validator(schemas[name]).validate(json.loads(call['function']['arguments']))
            return {'case': number, 'passed': True, 'elapsed_ms': round((time.perf_counter() - started) * 1000, 2),
                    'completion_tokens': body['usage']['completion_tokens'], 'finish_reason': choice['finish_reason']}
        except Exception as error:
            return {'case': number, 'passed': False, 'failure_type': type(error).__name__,
                    'elapsed_ms': round((time.perf_counter() - started) * 1000, 2)}
        finally:
            with lock:
                active -= 1
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        rows = list(executor.map(request, range(32)))
    elapsed = (time.perf_counter() - started) * 1000
    times = sorted(row['elapsed_ms'] for row in rows)
    data = {'label': label, 'scope': '16 路短 named-tool 请求，同一前缀；不等于满 16K 或持续负载吞吐',
            'workers': 16, 'peak_client_inflight': peak, 'samples': len(rows),
            'passed': sum(row['passed'] for row in rows), 'total_elapsed_ms': round(elapsed, 2),
            'latency_median_ms': statistics.median(times), 'latency_p95_ms': times[math.ceil(len(times) * .95) - 1],
            'results': rows}
    (ROOT / (label + '-concurrency.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('16 路短工具探针', label, data['passed'], '/', data['samples'], '客户端峰值=', peak, flush=True)
    assert data['passed'] == 32 and peak == 16

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', choices=['cache40_before', 'cache50_after'], required=True)
    run(parser.parse_args().label)
