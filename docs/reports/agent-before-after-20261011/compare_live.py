"""同一当前模型下重测新旧 Agent；只管理自建容器和独立测试 Session。"""
import argparse
import concurrent.futures
import datetime
import hashlib
import importlib.util
import json
import math
import secrets
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIVE = Path('/tmp/rs-agent-live-complex-concurrency-20261011')
QA = Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
sys.path.insert(0, str(LIVE))
from deploy_live import identity, inspect, NAME as SOURCE
from complex_probe import dependency_snapshot
from model_cache_metrics import read_cache_metrics as read_model_cache_metrics

NAME = 'rs-agent-ab-20261011'
PORT = 18318
BASE = f'http://127.0.0.1:{PORT}'
LABEL = 'rsagent.before-after-20261011'
MODEL_PORT = 18082
JARS = {
    'original': QA / 'rs-service-agent-baseline.jar',
    'pre-concurrency': LIVE / 'rs-service-agent.previous.jar',
    'current': Path('/tmp/rs-agent-concurrency-20261011/rs-service-agent.jar'),
}
CURRENT_SHA = '4bc94fc6894a65fb933071ac91c2506c5964542c68d464f59155967c027c1c76'
FLAGS = ('RS_AGENT_DIRECT_RECOMMENDATION_ENABLED', 'RS_AGENT_LLM_SYNTHESIS_ENABLED',
         'RS_AGENT_COMPACT_TOOL_SCHEMAS_ENABLED', 'RS_AGENT_MAX_ACTIVE_LOOPS',
         'RS_AGENT_MAX_MODEL_STREAMS', 'RS_AGENT_MODEL_STREAM_ACQUIRE_TIMEOUT_MS',
         'RS_AGENT_MAX_RECOMMENDATION_CALLS', 'RS_AGENT_RECOMMENDATION_ACQUIRE_TIMEOUT_MS',
         'RS_AGENT_MAX_TOOL_CALLS', 'RS_AGENT_MAX_SESSION_QUEUE_SIZE')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def target_identity():
    result = subprocess.run(['pgrep', '-af', 'vllm serve'], capture_output=True, text=True)
    return [line for line in result.stdout.splitlines() if '/bin/vllm serve ' in line and f'--port {MODEL_PORT} ' in line]


def read_cache_metrics():
    return read_model_cache_metrics(f'http://127.0.0.1:{MODEL_PORT}')


def cleanup():
    marker = ROOT / 'clone-state.json'
    state = json.loads(marker.read_text()) if marker.exists() else None
    result = subprocess.run(['docker', 'inspect', NAME], capture_output=True, text=True)
    if result.returncode == 0:
        row = json.loads(result.stdout)[0]
        assert state and state['name'] == NAME and row['Id'] == state['id']
        assert row['Config']['Labels'].get(LABEL) == 'true'
        subprocess.run(['docker', 'rm', '-f', NAME], check=True, capture_output=True)
    if state:
        state['cleaned'] = True
        marker.write_text(json.dumps(state, indent=2))
    (ROOT / 'clone.private.env').unlink(missing_ok=True)


def configure(version):
    cleanup()
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1', PORT)) != 0, '测试端口已被占用'
    source = inspect(SOURCE)
    assert source['State']['Running'] and not source['HostConfig']['Privileged']
    assert source['HostConfig']['NetworkMode'] == 'host'
    jar = JARS[version]
    sha = digest(jar)
    if version == 'current':
        assert sha == CURRENT_SHA
    env = dict(item.split('=', 1) for item in source['Config']['Env'] if '=' in item)
    assert env['RS_AGENT_OPENAI_BASE_URL'] == 'http://127.0.0.1:18082/v1'
    assert env['RS_AGENT_DIRECT_RECOMMENDATION_ENABLED'] == 'false'
    env.update(SERVER_PORT=str(PORT), SERVER_ADDRESS='127.0.0.1')
    env['RS_AGENT_OPENAI_BASE_URL'] = f'http://127.0.0.1:{MODEL_PORT}/v1'
    if version != 'current':
        # 历史版本的模型入口配置。新增推荐许可不属于原配置，旧构建忽略该变量。
        env.update(RS_AGENT_MAX_MODEL_STREAMS='8', RS_AGENT_MODEL_STREAM_ACQUIRE_TIMEOUT_MS='200',
                   RS_AGENT_MAX_RECOMMENDATION_CALLS='8')
    if version == 'original':
        env.update(RS_AGENT_LLM_SYNTHESIS_ENABLED='false', RS_AGENT_COMPACT_TOOL_SCHEMAS_ENABLED='false')
    else:
        assert env['RS_AGENT_LLM_SYNTHESIS_ENABLED'] == 'true'
    private = ROOT / 'clone.private.env'
    private.write_text('\n'.join(key + '=' + value for key, value in env.items()) + '\n')
    private.chmod(0o600)
    command = ['docker', 'run', '-d', '--name', NAME, '--network', 'host', '--memory', '3g',
               '--label', LABEL + '=true', '--env-file', str(private)]
    if source['Config'].get('User'):
        command += ['--user', source['Config']['User']]
    if source['Config'].get('WorkingDir'):
        command += ['--workdir', source['Config']['WorkingDir']]
    replacements = 0
    for mount in source['Mounts']:
        assert not mount['RW']
        mount_source = mount['Source']
        if mount_source.endswith('/rs-service-agent.jar'):
            mount_source = str(jar)
            replacements += 1
        command += ['--mount', f"type=bind,src={mount_source},dst={mount['Destination']},readonly"]
    assert replacements == 1
    command += [source['Config']['Image']] + source['Config']['Cmd']
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        (ROOT / 'clone-state.json').write_text(json.dumps(
            {'name': NAME, 'id': result.stdout.strip(), 'port': PORT, 'cleaned': False}))
    finally:
        private.unlink(missing_ok=True)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(BASE + '/actuator/health', timeout=3) as response:
                if json.load(response)['status'] == 'UP':
                    return {'version': version, 'jar_sha256': sha, 'model_port': MODEL_PORT,
                            'flags': {key: env.get(key, '(默认值)') for key in FLAGS}}
        except OSError:
            pass
        time.sleep(2)
    raise TimeoutError('独立 Agent 未就绪')


def request_json(url, account=None, payload=None, observer=False):
    headers = {'Content-Type': 'application/json'}
    if account:
        headers.update(Authorization='Bearer ' + account['accessToken'],
                       **{'X-Account-Id': account['accountId'], 'X-Profile-User-Id': account['profileUserId']})
    if observer:
        headers['X-User-Roles'] = 'OBSERVER'
    request = urllib.request.Request(url, headers=headers,
        data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode())
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def metric_window(before, after):
    delta = {key: after[key] - value for key, value in before.items()
             if key in after and not key.startswith('vllm:num_requests_')}
    result = {'before': before, 'after': after, 'delta': delta,
              'scope': '共享模型窗口的累计指标差，未按 request_id 关联'}
    count = delta.get('vllm:time_to_first_token_seconds_count', 0)
    result['observed_model_calls'] = count
    queried = delta.get('vllm:prefix_cache_queries_total')
    hit = delta.get('vllm:prefix_cache_hits_total')
    valid = count > 0 and all(value >= 0 for value in delta.values())
    valid &= all(delta.get(name + '_count') == count for name in (
        'vllm:request_prompt_tokens', 'vllm:request_queue_time_seconds', 'vllm:request_prefill_time_seconds'))
    valid &= queried is not None and hit is not None and queried == delta.get('vllm:request_prompt_tokens_sum')
    valid &= queried is not None and queried > 0 and hit is not None and 0 <= hit <= queried
    result['internally_consistent'] = bool(valid)
    if valid:
        result.update(input_tokens=int(queried), cached_tokens=int(hit),
            cache_hit_percent=round(100 * hit / queried, 2),
            mean_model_ttft_ms=round(1000 * delta['vllm:time_to_first_token_seconds_sum'] / count, 3),
            mean_model_queue_ms=round(1000 * delta['vllm:request_queue_time_seconds_sum'] / count, 3),
            mean_model_prefill_ms=round(1000 * delta['vllm:request_prefill_time_seconds_sum'] / count, 3))
    return result


def sample(account, query, session):
    row = {'query': query, 'passed': False}
    start = time.perf_counter()
    try:
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + account['accessToken'],
            'X-Account-Id': account['accountId'], 'X-Profile-User-Id': account['profileUserId']}
        payload = {'session_id': session, 'profile_user_id': account['profileUserId'], 'user_message': query,
            'limit': 5, 'context': {'scene': 'agent_chat', 'client_turn_id': 'ab-' + secrets.token_hex(12), 'a2ui_state': []}}
        request = urllib.request.Request(BASE + '/api/agent/chat/stream', headers=headers,
            data=json.dumps(payload, ensure_ascii=False).encode())
        counts = {}; event = ''; final = None; error = None
        start = time.perf_counter()
        with urllib.request.urlopen(request, timeout=180) as response:
            for raw in response:
                line = raw.decode().strip()
                if line.startswith('event:'):
                    event = line[6:].strip()
                if not line.startswith('data:'):
                    continue
                data = json.loads(line[5:].strip())
                elapsed = round(1000 * (time.perf_counter() - start), 2)
                counts[event] = counts.get(event, 0) + 1
                if event == 'answer_block' and data.get('type') == 'text' and str(data.get('content', '')).strip():
                    row.setdefault('first_text_block_ms', elapsed)
                if event == 'token' and str(data.get('delta', '')).strip():
                    row.setdefault('first_public_token_ms', elapsed)
                if event == 'done':
                    final = data.get('response')
                    row['done_event_ms'] = elapsed
                if event == 'error':
                    error = data
        row.update(agent_done_ms=round(1000 * (time.perf_counter() - start), 2), sse_event_counts=counts,
                   error_code=(error or {}).get('error_code', (error or {}).get('code')))
        if not final or error:
            return row
        ids = final.get('recommended_item_ids')
        if ids is None:
            ids = [item['item_id'] for item in final.get('recommended_items', [])]
        catalog = request_json('http://127.0.0.1:18288/api/catalog/items/batch', account, {'item_ids': ids})
        row['complete_ms'] = round(1000 * (time.perf_counter() - start), 2)
        history = request_json(BASE + '/api/agent/sessions/' + session + '/history', account)
        card = final.get('card_set_id', final.get('cardSetId'))
        trace = request_json('http://127.0.0.1:18213/api/platform/recommend/' + card + '/trace') if card else {}
        turns = request_json(BASE + '/api/platform/agent/' + session + '/turns', observer=True).get('turns', [])
        tools = turns[-1].get('tool_calls', turns[-1].get('toolCalls', [])) if turns else []
        failed = sum(tool.get('status') in ('FAILED', 'ERROR', 'UNAVAILABLE') for tool in tools)
        stages = trace.get('stage_counts') or {}
        row.update(items=len(ids), answer_chars=len(final.get('assistant_message', '')),
            tool_names=[tool.get('tool_name', tool.get('toolName')) for tool in tools], failed_tools=failed,
            stage_counts=stages, degradation_reasons=final.get('degradation_reasons'))
        row['failed_tool_codes'] = [{'tool_name': tool.get('tool_name', tool.get('toolName')),
            'error_code': tool.get('error_code', (tool.get('error') or {}).get('code') if isinstance(tool.get('error'), dict) else None)}
            for tool in tools if tool.get('status') in ('FAILED', 'ERROR', 'UNAVAILABLE')]
        checks = {'complete': bool(final) and not error,
            'five_real_unique_items': len(ids) == len(set(ids)) == len(catalog) == 5
                and {item['item_id'] for item in catalog} == set(ids),
            'text_and_history': row['answer_chars'] > 0 and bool(history.get('turns'))
                and history['turns'][-1].get('finish_reason') == 'FINAL_ANSWER',
            'tools_without_failure': failed == 0,
            'deepfm_bge': stages.get('deepfm_scored', 0) > 0 and stages.get('bge_reranked', 0) > 0,
            'no_degradation': final.get('degradation_reasons') == [] and trace.get('config', {}).get('ranking_degraded') == 0}
        row.update(checks=checks, passed=all(checks.values()))
    except Exception as error:
        row.update(error_type=type(error).__name__, failed_elapsed_ms=round(1000 * (time.perf_counter() - start), 2))
    return row


def distribution(rows):
    values = sorted(row['complete_ms'] for row in rows if row['passed'])
    return {'total': len(rows), 'passed': len(values), 'failed': len(rows) - len(values),
        'successful_mean_ms': round(statistics.mean(values), 2) if values else None,
        'successful_median_ms': round(statistics.median(values), 2) if values else None,
        'successful_p95_ms': values[max(0, math.ceil(len(values) * .95) - 1)] if values else None,
        'successful_max_ms': max(values) if values else None}


def main():
    global MODEL_PORT
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('inventory', 'latency', 'capacity'))
    parser.add_argument('--version', choices=tuple(JARS), default='current')
    parser.add_argument('--name', default='comparison')
    parser.add_argument('--ordinary-samples', type=int, default=3)
    parser.add_argument('--ordinary-only', action='store_true')
    parser.add_argument('--levels', default='8,16')
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--model-port', type=int, choices=(18082, 18096), default=18082)
    args = parser.parse_args()
    MODEL_PORT = args.model_port
    assert args.name.replace('-', '').isalnum()
    if args.phase == 'inventory':
        data = {'model': identity(), 'dependencies': dependency_snapshot(),
                'jars': {key: {'path': str(path), 'sha256': digest(path)} for key, path in JARS.items()},
                'model_metrics': read_cache_metrics()}
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    assert 1 <= args.ordinary_samples <= 8 and 1 <= args.repeats <= 3
    levels = [int(level) for level in args.levels.split(',')]
    assert all(1 <= level <= 16 for level in levels)
    destination = ROOT / (args.name + '.json')
    assert not destination.exists(), '不覆盖既有对照证据'
    report = {'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'phase': args.phase, 'version': args.version, 'model_before': identity(),
        'target_model_before': target_identity(),
        'dependencies_before': dependency_snapshot(), 'cases': [], 'stages': [],
        'scope': '独立 Agent、真实当前 GPU1 模型和共享下游；独立 Session，非线上网关或浏览器耗时；非最大持续容量',
        'model_comparison_scope': '模型量化、缓存预算、权重和参数固定，仅比较 Agent 版本及对应编排配置',
        'quality_scope': '完整商品、正文、持久历史、DeepFM/BGE 与工具无失败；不替代解释语义人工回归'}
    def save():
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    def stable():
        if identity() != report['model_before'] or dependency_snapshot() != report['dependencies_before']:
            raise RuntimeError('共享模型或依赖身份已改变，停止对照')
        if target_identity() != report['target_model_before']:
            raise RuntimeError('对照模型身份已改变，停止测试')
    save()
    try:
        report['configuration'] = configure(args.version)
        spec = importlib.util.spec_from_file_location('business_probe', '/tmp/rs-agent-quantization-retry-20261011/business_probe.py')
        probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
        users = probe.accounts()
        def create_session(index):
            return probe.http('/api/sessions', {'entryScene': 'before-after-benchmark'}, users[index % len(users)]['accessToken'])['sessionId']
        def serial(query, label, index=0, session=None):
            stable()
            session = session or create_session(index)
            before = read_cache_metrics()
            first_call = {}
            stop = threading.Event()
            def watch_first_call():
                while not stop.wait(0.05):
                    try:
                        current = read_cache_metrics()
                        count = current.get('vllm:time_to_first_token_seconds_count', 0) - before.get('vllm:time_to_first_token_seconds_count', 0)
                        if count > 0:
                            if count == 1:
                                first_call['first_model_call_ttft_ms'] = round(1000 * (
                                    current['vllm:time_to_first_token_seconds_sum'] - before['vllm:time_to_first_token_seconds_sum']), 3)
                            first_call['first_observed_model_count'] = count
                            break
                    except OSError:
                        pass
            watcher = threading.Thread(target=watch_first_call, daemon=True)
            watcher.start()
            try:
                row = sample(users[index % len(users)], query, session)
            finally:
                stop.set(); watcher.join(6)
            row.update(first_call)
            row.update(label=label, concurrent_requests=1, model_metrics=metric_window(before, read_cache_metrics()))
            report['cases'].append(row); save()
            print(json.dumps({'version': args.version, 'label': label, 'passed': row['passed'],
                'complete_ms': row.get('complete_ms'), 'error_code': row.get('error_code'),
                'model_calls': row['model_metrics']['observed_model_calls']}, ensure_ascii=False), flush=True)
            stable()
            return row, session
        warm, _ = serial('推荐鼠标', 'warmup')
        if args.phase == 'latency':
            for index in range(args.ordinary_samples):
                serial('推荐鼠标', 'ordinary-' + str(index), index)
            if not args.ordinary_only:
                serial('推荐一款适合办公的鼠标，最好静音，说明理由', 'complex-office', 0)
                serial('推荐适合编程使用的键盘，说明各自的区别', 'complex-keyboard', 0)
                session = create_session(1)
                for index, query in enumerate(('请帮我推荐鼠标', '换一批鼠标，适合办公使用', '再推荐五款鼠标，说明理由')):
                    row, _ = serial(query, 'multi-' + str(index), 1, session)
                    if not row['passed']:
                        report['multi_sequence_stopped_on_quality_failure'] = True
                        save(); break
        else:
            assert warm['passed'], '单请求不合格，不启动并发压测'
            for repeat in range(args.repeats):
                for count in levels:
                    stable()
                    sessions = [create_session(index) for index in range(count)]
                    barrier = threading.Barrier(count)
                    before = read_cache_metrics()
                    begin = time.perf_counter()
                    def run(index):
                        barrier.wait(timeout=15)
                        row = sample(users[index % len(users)], '推荐鼠标', sessions[index])
                        row['index'] = index
                        return row
                    with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
                        rows = list(pool.map(run, range(count)))
                    elapsed = time.perf_counter() - begin
                    stage = {'repeat': repeat, 'concurrent_requests': count,
                        'distinct_accounts': min(count, len(users)), 'distinct_sessions': len(set(sessions)),
                        'batch_wall_ms': round(elapsed * 1000, 2), 'cases': rows,
                        'model_metrics': metric_window(before, read_cache_metrics()), **distribution(rows)}
                    stage['completed_requests_per_second'] = round(stage['passed'] / elapsed, 4)
                    report['stages'].append(stage); save()
                    print(json.dumps({key: value for key, value in stage.items() if key not in ('cases', 'model_metrics')},
                                     ensure_ascii=False), flush=True)
                    stable()
        report['completed'] = True
    except Exception as error:
        report.update(completed=False, error_type=type(error).__name__)
        print(json.dumps({'completed': False, 'error_type': type(error).__name__}), flush=True)
    finally:
        cleanup()
        report.update(model_after=identity(), dependencies_after=dependency_snapshot())
        report['target_model_after'] = target_identity()
        report['target_model_process_unchanged'] = report['target_model_before'] == report['target_model_after']
        report['model_process_unchanged'] = report['model_before'] == report['model_after']
        report['dependencies_stable'] = report['dependencies_before'] == report['dependencies_after']
        report['clone_cleaned'] = subprocess.run(['docker', 'inspect', NAME], capture_output=True).returncode != 0
        save()


if __name__ == '__main__':
    main()
