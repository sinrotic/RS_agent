"""同输入调度对照：只保存公开计时、token 用量及输出摘要。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

from jsonschema import Draft202012Validator

sys.path.insert(0, '/tmp/rs-agent-quantization-retry-20261011')
from benchmark_core import measure, payload, metrics, SYSTEM, SCHEMA

ROOT = Path(__file__).resolve().parent

def percentile(values, fraction=.95):
    values = sorted(values)
    return values[min(len(values) - 1, int((len(values) - 1) * fraction + .5))]

def checked(base, body, scenario, fixed=False):
    body = {**body, 'seed': 0}
    row = measure(base, body, scenario, fixed_decode=fixed)
    if not fixed:
        Draft202012Validator(SCHEMA).validate(row['parsed_output'])
    row['input_sha256'] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    row['output_sha256'] = hashlib.sha256(row.pop('raw_output').encode()).hexdigest()
    row.pop('parsed_output')
    row['passed'] = True
    return row

def batch(base, bodies, scenario):
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(bodies)) as executor:
        rows = list(executor.map(lambda body: checked(base, body, scenario), bodies))
    return {'elapsed_seconds': time.perf_counter() - started, 'rows': rows}

def summarize(rounds):
    selected = [row for item in rounds if not item['warmup'] for row in item['rows']]
    elapsed = sum(item['elapsed_seconds'] for item in rounds if not item['warmup'])
    return {'samples': len(selected), 'passed': sum(row['passed'] for row in selected),
        'e2e_median_ms': statistics.median(row['e2e_seconds'] for row in selected) * 1000,
        'e2e_p95_ms': percentile([row['e2e_seconds'] for row in selected]) * 1000,
        'first_content_median_ms': statistics.median(row['first_content_seconds'] for row in selected) * 1000,
        'successful_requests_per_second': len(selected) / elapsed,
        'completion_tokens_per_second': sum(row['usage']['completion_tokens'] for row in selected) / elapsed,
        'completion_tokens_median': statistics.median(row['usage']['completion_tokens'] for row in selected)}

def run(base, label):
    artifact = ROOT / (label + '-performance.json')
    assert not artifact.exists(), '不覆盖既有测量'
    before = metrics(base)
    assert before['num_requests_running'] == before['num_requests_waiting'] == 0
    tests = {}
    # 单独保留启动后的首次 16 路突发；后续多轮统计仍用于稳态对照。
    first = batch(base, [payload('qwen35-4b', tool=True)] * 16, 'first_burst16')
    first.update(repeat=0, warmup=False)
    tests['first_burst16'] = {'rounds': [first], 'summary': summarize([first])}
    for concurrency in [1, 4, 8, 16]:
        rounds = []
        for repeat in range(4):
            item = batch(base, [payload('qwen35-4b', tool=True)] * concurrency, 'warm_tool')
            item.update(repeat=repeat, warmup=repeat == 0)
            rounds.append(item)
        tests['warm_tool_c' + str(concurrency)] = {'rounds': rounds, 'summary': summarize(rounds)}
        print(label, 'warm_tool', concurrency, round(tests['warm_tool_c' + str(concurrency)]['summary']['e2e_median_ms'], 2), flush=True)
    for concurrency in [4, 8, 16]:
        rounds = []
        for repeat in range(4):
            bodies = []
            for number in range(concurrency):
                if number % 4 == 0:
                    # 跨候选输入相同；每个批次使用独立长前缀，避免前一轮缓存掩盖 prefill。
                    prefix = f'隔离调度测量 c{concurrency} r{repeat} n{number}。\n'
                    prefix += '\n'.join(f'资料{i:03d}：这是虚构的占位资料，只用于性能测试，不是商品事实。' for i in range(260))
                    bodies.append(payload('qwen35-4b', prefix + '\n' + SYSTEM))
                else:
                    bodies.append(payload('qwen35-4b', tool=True))
            item = batch(base, bodies, 'mixed_long_short')
            item.update(repeat=repeat, warmup=repeat == 0)
            rounds.append(item)
        tests['mixed_c' + str(concurrency)] = {'rounds': rounds, 'summary': summarize(rounds)}
        print(label, 'mixed', concurrency, round(tests['mixed_c' + str(concurrency)]['summary']['e2e_median_ms'], 2), flush=True)
    decode = [checked(base, payload('qwen35-4b', decode=True), 'decode128', True) for _ in range(6)]
    tests['decode128'] = {'rows': decode, 'e2e_median_ms': statistics.median(row['e2e_seconds'] for row in decode) * 1000}
    # 小规模开放到达，记录实际发送时间；不把固定并发结果称作持续容量 SLA。
    arrivals = []
    origin = time.perf_counter()
    def arrived(number):
        scheduled = origin + number / 4
        actual = time.perf_counter()
        row = checked(base, payload('qwen35-4b', tool=True), 'arrival4rps')
        row['arrival_index'] = number
        row['scheduled_offset_seconds'] = number / 4
        row['arrival_lag_seconds'] = max(0, actual - scheduled)
        return row
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = []
        for number in range(24):
            time.sleep(max(0, origin + number / 4 - time.perf_counter()))
            futures.append(executor.submit(arrived, number))
        arrivals = [future.result() for future in futures]
    total = time.perf_counter() - origin
    tests['arrival4rps'] = {'offered_requests_per_second': 4, 'samples': 24, 'duration_seconds': total,
        'successful_requests_per_second': 24 / total, 'e2e_p95_ms': percentile([row['e2e_seconds'] for row in arrivals]) * 1000,
        'rows': arrivals}
    report = {'label': label, 'scope': '同机小规模模型调度对照，首可见内容不是逐 token TTFT；含冷前缀混合和短请求开放到达，非长期容量 SLA',
        'base_url': base, 'initial_metrics': before, 'final_metrics': metrics(base), 'tests': tests}
    artifact.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if label in ['production_after', 'production_final_after', 'production_matched_after']:
        before_label = {'production_after': 'production_before', 'production_final_after': 'production_retry_before',
                        'production_matched_after': 'production_control'}[label]
        baseline = json.loads((ROOT / (before_label + '-performance.json')).read_text())['tests']
        tails = {key: value['summary']['e2e_p95_ms'] / baseline[key]['summary']['e2e_p95_ms']
                 for key, value in tests.items() if key.startswith(('warm_tool_', 'mixed_'))}
        report['production_tail_ratios'] = tails
        artifact.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        assert max(tails.values()) <= 1.20, '正式同卡 P95 退化超过 20%，触发恢复前一版'
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    run(args.base_url, args.label)
