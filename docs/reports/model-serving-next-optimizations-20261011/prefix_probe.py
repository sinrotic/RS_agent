"""真实冻结前缀的首 token 响应对照；1 token 仅用于预热/计时，不执行工具。"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import statistics
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
OLD = Path('/tmp/rs-agent-quantization-retry-20261011')
PARTIAL = Path('/tmp/rs-agent-partial-quantization-20261011')

def fixtures():
    final = json.loads((OLD / 'replay-payloads.private.json').read_text())
    planning = json.loads((PARTIAL / 'planning-dataset.private.json').read_text())
    records = final[:2] + [{'profile': 'planning_' + str(i), 'payload': item['payload']} for i, item in enumerate(planning[:6])]
    assert len(records) == 8
    return records

def build():
    path = ROOT / 'expanded-prefixes.private.json'
    if not path.exists():
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'w') as handle:
            json.dump(fixtures(), handle, ensure_ascii=False)
    return path

def run(base, label):
    rows = []
    for number, item in enumerate(fixtures()):
        body = copy.deepcopy(item['payload'])
        for key in ['stream_options', 'max_completion_tokens', 'min_tokens']:
            body.pop(key, None)
        body.update(model='qwen35-4b', max_tokens=1, n=1, temperature=0, seed=0, stream=False)
        for repeat in range(2):
            started = time.perf_counter()
            request = urllib.request.Request(base + '/chat/completions', data=json.dumps(body).encode(),
                                             headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.load(response)
            assert result['usage']['completion_tokens'] == 1
            rows.append({'case': number, 'profile': item['profile'], 'repeat': repeat,
                'input_sha256': hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
                'elapsed_ms': (time.perf_counter() - started) * 1000, 'usage': result['usage'], 'passed': True})
    first = [row['elapsed_ms'] for row in rows if row['repeat'] == 0 and row['case'] >= 2]
    report = {'label': label, 'scope': '六条真实规划前缀及两条最终回答，固定1token响应计时；非完整回答验收、不执行工具',
        'planning_first_response_median_ms': statistics.median(first), 'samples': len(rows), 'rows': rows}
    (ROOT / (label + '-prefix.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(label, '规划前缀1token响应中位数', round(report['planning_first_response_median_ms'], 2), 'ms', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--base-url')
    parser.add_argument('--label')
    args = parser.parse_args()
    if args.build:
        build()
    else:
        run(args.base_url, args.label)
