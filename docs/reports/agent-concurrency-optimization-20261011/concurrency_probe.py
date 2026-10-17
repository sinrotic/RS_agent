"""真实模型、多账号独立 Session 的并发阶梯；仅管理本次验收容器。"""
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import re
import statistics
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = 'rs-concurrency-20261011-agent'
SOURCE = 'rs-e2e-857e8b14-agent-fast'
PORT = 18316
LABEL = 'rsagent.concurrency-task'


def identity():
    lines = subprocess.check_output(['pgrep', '-af', 'vllm serve'], text=True).splitlines()
    return [line for line in lines if '/bin/vllm serve ' in line]


def cleanup():
    marker = ROOT / 'clone-state.json'
    if marker.exists():
        state = json.loads(marker.read_text())
        assert state['name'] == NAME and state['port'] == PORT
        current = subprocess.run(['docker', 'inspect', NAME], capture_output=True, text=True)
        if current.returncode == 0:
            config = json.loads(current.stdout)[0]
            assert config['Config']['Labels'].get(LABEL) == '20261011'
            subprocess.run(['docker', 'rm', '-f', NAME], check=True, stdout=subprocess.DEVNULL)
        state['cleaned'] = True
        marker.write_text(json.dumps(state, indent=2))
    (ROOT / 'clone.private.env').unlink(missing_ok=True)


def configure(jar, slots, wait_ms, recommendation_slots=8):
    current = subprocess.run(['docker', 'inspect', NAME], capture_output=True, text=True)
    if current.returncode == 0:
        assert (ROOT / 'clone-state.json').exists(), '拒绝覆盖无法核验的实例'
        cleanup()
    config = json.loads(subprocess.check_output(['docker', 'inspect', SOURCE], text=True))[0]
    env = dict(item.split('=', 1) for item in config['Config']['Env'] if '=' in item)
    assert env['RS_AGENT_OPENAI_BASE_URL'] == 'http://127.0.0.1:18082/v1'
    assert env['RS_AGENT_DIRECT_RECOMMENDATION_ENABLED'] == 'false'
    assert env['RS_AGENT_LLM_SYNTHESIS_ENABLED'] == 'true'
    source_limits = {key: env.get(key, '(使用配置默认值)') for key in (
        'RS_AGENT_MAX_ACTIVE_LOOPS', 'RS_AGENT_ACTIVE_LOOP_ACQUIRE_TIMEOUT_MS',
        'RS_AGENT_MAX_MODEL_STREAMS', 'RS_AGENT_MODEL_STREAM_ACQUIRE_TIMEOUT_MS',
        'RS_AGENT_MAX_TOOL_CALLS', 'RS_AGENT_MAX_SESSION_QUEUE_SIZE', 'RS_AGENT_MAX_RECOMMENDATION_CALLS',
        'RS_AGENT_RECOMMENDATION_ACQUIRE_TIMEOUT_MS', 'SPRING_PROFILES_ACTIVE')}
    env.update(SERVER_PORT=str(PORT), SERVER_ADDRESS='127.0.0.1',
               RS_AGENT_MAX_MODEL_STREAMS=str(slots), RS_AGENT_MODEL_STREAM_ACQUIRE_TIMEOUT_MS=str(wait_ms),
               RS_AGENT_MAX_RECOMMENDATION_CALLS=str(recommendation_slots))
    envfile = ROOT / 'clone.private.env'
    envfile.write_text('\n'.join(key + '=' + value for key, value in env.items()) + '\n')
    envfile.chmod(0o600)
    command = ['docker', 'run', '-d', '--name', NAME, '--network', 'host', '--memory', '3g',
               '--label', LABEL + '=20261011', '--env-file', str(envfile)]
    replacements = 0
    for mount in config['Mounts']:
        assert not mount['RW']
        source = mount['Source']
        if source.endswith('/rs-service-agent.jar'):
            source = str(jar)
            replacements += 1
        command += ['--mount', 'type=bind,src=' + source + ',dst=' + mount['Destination'] + ',readonly']
    assert replacements == 1 and jar.is_file()
    command += [config['Config']['Image']] + config['Config']['Cmd']
    (ROOT / 'clone-state.json').write_text(json.dumps({'name': NAME, 'port': PORT, 'cleaned': False}))
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    finally:
        envfile.unlink(missing_ok=True)
    deadline = time.monotonic() + 90
    while True:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/actuator/health', timeout=3) as response:
                assert json.load(response)['status'] == 'UP'
            return source_limits
        except (OSError, AssertionError):
            if time.monotonic() >= deadline:
                raise TimeoutError('验收 Agent 未就绪')
            time.sleep(2)


def model_metrics():
    with urllib.request.urlopen('http://127.0.0.1:18082/metrics', timeout=3) as response:
        value = response.read().decode()
    result = {}
    for metric in ('num_requests_running', 'num_requests_waiting', 'num_preemptions_total'):
        matches = re.findall(r'^vllm:' + metric + r'(?:\{[^}]*\})?\s+([0-9.eE+-]+)', value, re.MULTILINE)
        result[metric] = sum(float(match) for match in matches) if matches else None
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('name')
    parser.add_argument('--slots', type=int, default=8)
    parser.add_argument('--wait-ms', type=int, default=200)
    parser.add_argument('--recommendation-slots', type=int, default=8)
    parser.add_argument('--levels', default='8,16')
    parser.add_argument('--jar', default='/tmp/rs-agent-orchestration-20261011/rs-service-agent.jar')
    parser.add_argument('--cleanup', action='store_true')
    args = parser.parse_args()
    if args.cleanup:
        cleanup()
        return
    assert re.fullmatch('[a-z0-9-]+', args.name)
    assert 1 <= args.slots <= 32 and 0 <= args.wait_ms <= 60000
    assert 1 <= args.recommendation_slots <= 32
    levels = [int(value) for value in args.levels.split(',')]
    assert all(1 <= value <= 32 for value in levels)
    report = {'name': args.name, 'model_before': identity(), 'model_slots': args.slots,
              'model_wait_ms': args.wait_ms, 'recommendation_slots': args.recommendation_slots,
              'agent_sha256': hashlib.file_digest(Path(args.jar).open('rb'), 'sha256').hexdigest(),
              'scope': '真实 Agent、LLM、推荐、目录与持久历史；8 个真实账号的独立 Session',
              'stages': [], 'metric_limit': '模型全局指标可能包含其他共享请求；本实验未测持续最大容量或生产 P95'}
    destination = ROOT / (args.name + '.json')
    def save():
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    save()
    try:
        report['source_limits'] = configure(Path(args.jar), args.slots, args.wait_ms, args.recommendation_slots)
        spec = importlib.util.spec_from_file_location('business_probe', '/tmp/rs-agent-quantization-retry-20261011/business_probe.py')
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)
        probe.BASE = f'http://127.0.0.1:{PORT}'
        assert (probe.ROOT / 'accounts.json').is_file()
        users = probe.accounts()
        def sample(index, session, label):
            entry = {'index': index}
            try:
                row = probe.one(users[index % len(users)], '推荐鼠标', 'fast', label, session)
                final = row.get('response') or {}
                ids = [item['item_id'] for item in final.get('recommended_items', [])]
                history = row.get('history', {}).get('turns', [])
                trace = row.get('recommend_trace') or {}
                entry.update(complete_ms=row.get('complete_with_catalog_ms'), agent_ms=row['agent_done_ms'],
                             items=len(ids), answer_chars=len(final.get('assistant_message', '')),
                             finish_reason=history[-1].get('finish_reason') if history else None,
                             error_code=(row.get('error') or {}).get('error_code', (row.get('error') or {}).get('code')),
                             error_status=(row.get('error') or {}).get('status'),
                             degradation_reasons=final.get('degradation_reasons'),
                             stage_counts=trace.get('stage_counts'),
                             no_degradation=final.get('degradation_reasons') == []
                                and trace.get('config', {}).get('ranking_degraded') == 0,
                             deepfm_bge=trace.get('stage_counts', {}).get('deepfm_scored', 0) > 0
                                and trace.get('stage_counts', {}).get('bge_reranked', 0) > 0)
                entry['passed'] = bool(final) and not row.get('error') and len(ids) == len(set(ids)) == len(row.get('catalog', [])) == 5
                entry['passed'] &= entry['finish_reason'] == 'FINAL_ANSWER' and entry['answer_chars'] > 0 and entry['no_degradation'] and entry['deepfm_bge']
            except Exception as error:
                entry.update(passed=False, error_type=type(error).__name__)
            return entry
        warm = probe.http('/api/sessions', {'entryScene': 'concurrency-warmup'}, users[0]['accessToken'])['sessionId']
        report['warmup'] = sample(0, warm, args.name + '-warmup')
        assert report['warmup']['passed'], '单请求未通过，不启动并发阶梯'
        for count in levels:
            sessions = [probe.http('/api/sessions', {'entryScene': 'concurrency-benchmark'},
                                   users[index % len(users)]['accessToken'])['sessionId'] for index in range(count)]
            barrier = threading.Barrier(count)
            stop = threading.Event()
            observations = []
            before = model_metrics()
            def monitor():
                while not stop.wait(0.2):
                    try:
                        observations.append(model_metrics())
                    except OSError:
                        pass
            watcher = threading.Thread(target=monitor, daemon=True)
            def run(index):
                barrier.wait(timeout=10)
                return sample(index, sessions[index], args.name + '-c' + str(count) + '-' + str(index))
            watcher.start()
            begin = time.perf_counter()
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
                    rows = list(pool.map(run, range(count)))
            finally:
                elapsed = time.perf_counter() - begin
                stop.set()
                watcher.join(5)
            after = model_metrics()
            latencies = sorted(row['complete_ms'] for row in rows if row['passed'])
            stage = {'concurrent_requests': count, 'distinct_accounts': min(count, len(users)),
                     'distinct_sessions': len(set(sessions)), 'passed': len(latencies), 'failed': count - len(latencies),
                     'batch_wall_ms': round(elapsed * 1000, 2),
                     'completed_requests_per_second': round(len(latencies) / elapsed, 3),
                     'median_ms': round(statistics.median(latencies), 2) if latencies else None,
                     'maximum_ms': max(latencies) if latencies else None,
                     'peak_model_running': max((value['num_requests_running'] or 0 for value in observations), default=None),
                     'peak_model_waiting': max((value['num_requests_waiting'] or 0 for value in observations), default=None),
                     'model_preemptions_delta': after['num_preemptions_total'] - before['num_preemptions_total']
                         if before['num_preemptions_total'] is not None and after['num_preemptions_total'] is not None else None,
                     'cases': rows}
            report['stages'].append(stage)
            save()
            print(args.name, '并发', count, '完成', len(latencies), '/', count,
                  '完成吞吐', stage['completed_requests_per_second'], '/s；中位耗时', stage['median_ms'], flush=True)
        report['model_after'] = identity()
        report['model_process_unchanged'] = report['model_before'] == report['model_after']
        save()
    finally:
        cleanup()


if __name__ == '__main__':
    main()
