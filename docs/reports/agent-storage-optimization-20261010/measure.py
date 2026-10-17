"""按阶段保存全链路样本与匿名方法计时；失败也保留。"""
import argparse
import concurrent.futures
import json
import subprocess
import time
import urllib.request
from probe import ROOT, accounts, one

PORTS = (18202, 18205, 18201, 18208, 18213, 18214, 18288, 18215)

def ready():
    for _ in range(55):
        pending = []
        for port in PORTS:
            try:
                path = '/health' if port == 18215 else '/actuator/health'
                with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=2) as response:
                    result = json.load(response)
                if port != 18215 and result.get('status') != 'UP': pending.append(port)
            except Exception: pending.append(port)
        if not pending: return
        time.sleep(1)
    raise RuntimeError(f'服务未就绪: {pending}')

def capture(name, start):
    state = json.loads((ROOT / 'state.json').read_text())
    result = {}
    for label in ('agent-fast', 'recommend-fast', 'user', 'model'):
        process = subprocess.run(['docker', 'logs', '--since', str(int(start)), state[label]],
                                 text=True, capture_output=True, check=True)
        lines = process.stdout.splitlines() + process.stderr.splitlines()
        profiles = [json.loads(line.split('RS_PROFILE ', 1)[1]) for line in lines if 'RS_PROFILE {' in line]
        errors = [line for line in lines if any(term in line for term in
                   ('RS_PROFILE_TRANSFORM_FAILED', 'RS_PROFILE_STACK_ERROR', 'VerifyError'))]
        assert not errors, errors
        for profile in profiles:
            nodes = profile['nodes']
            assert nodes and nodes[0]['parent'] == -1
            assert all(n['duration_ns'] >= 0 and n['exclusive_ns'] >= 0 for n in nodes)
            assert sum(n['exclusive_ns'] for n in nodes) == nodes[0]['duration_ns'], '互斥计时必须闭合'
        result[label] = profiles
        (ROOT / f'{name}-{label}-stages.log').write_text('\n'.join(line for line in lines
                    if '推荐轮次耗时' in line or '推荐阶段耗时' in line))
    (ROOT / f'{name}-spans.json').write_text(json.dumps(result, indent=2))
    print('匿名计时保存', {k: len(v) for k, v in result.items()}, flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('name')
    parser.add_argument('--cold-variants', action='store_true')
    parser.add_argument('--quick', action='store_true')
    args = parser.parse_args()
    ready(); users = accounts(); start = time.time()
    result = {'first': [], 'warmups': [], 'single': [], 'concurrent_8': [], 'cold_variants_8': [], 'failures': []}
    def save(): (ROOT / f'{args.name}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    def sample(user, query, label):
        try: return one(user, query, 'fast', label)
        except Exception as error:
            failure = {'label': label, 'query': query, 'error': str(error)}
            print('测量失败', failure, flush=True)
            return failure
    def collect(group, samples):
        for row in samples:
            if row.get('response'): result[group].append(row)
            else: result['failures'].append(row)
        save()
    collect('first', [sample(users[0], '推荐鼠标', 'first')])
    collect('warmups', [sample(user, '推荐鼠标', f'warmup-{i}') for i, user in enumerate(users)])
    collect('single', [sample(users[0], '推荐鼠标', f'single-{i}') for i in range(4 if args.quick else 8)])
    if not args.quick:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            collect('concurrent_8', list(pool.map(lambda user: sample(user, '推荐鼠标', 'concurrent-8'), users)))
    if args.cold_variants:
        queries = ['推荐鼠标！', '请推荐鼠标', '给我推荐鼠标', '帮我推荐鼠标',
                   '推荐几款鼠标', '请给我推荐鼠标', '推荐一些鼠标', '请帮我推荐鼠标']
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            collect('cold_variants_8', list(pool.map(lambda pair: sample(pair[0], pair[1], 'cold-variants-8'), zip(users, queries))))
    capture(args.name, start)
    metrics = urllib.request.urlopen('http://127.0.0.1:18213/actuator/prometheus', timeout=3).read().decode()
    (ROOT / f'{args.name}-cache-metrics.txt').write_text('\n'.join(line for line in metrics.splitlines()
                                if 'recommend_query_embedding' in line or 'recommend_bge_scores' in line))
    print('评测阶段完成', args.name, '失败数', len(result['failures']), flush=True)

if __name__ == '__main__': main()
