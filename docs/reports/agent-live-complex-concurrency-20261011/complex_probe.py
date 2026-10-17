"""现有网关与单活 Agent 的真实复杂推荐阶梯；只发布脱敏聚合与属性结果。"""
import argparse
import concurrent.futures
import importlib.util
import json
import re
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from deploy_live import NAME, SHA, PARAMETERS, identity, inspect

ROOT = Path(__file__).resolve().parent
QUERIES = ('推荐一款适合办公的鼠标，最好静音，说明理由', '推荐适合编程使用的键盘，说明各自的区别')


def dependency_snapshot():
    names = (NAME, 'rs-e2e-857e8b14-recommend-fast', 'rs-e2e-857e8b14-model',
             'rs-e2e-857e8b14-gateway', 'rs-e2e-857e8b14-catalog')
    return {name: {'id': inspect(name)['Id'], 'started': inspect(name)['State']['StartedAt']} for name in names}


def model_metrics():
    with urllib.request.urlopen('http://127.0.0.1:18082/metrics', timeout=3) as response:
        text = response.read().decode()
    result = {}
    for metric in ('num_requests_running', 'num_requests_waiting', 'num_preemptions_total'):
        values = re.findall(r'^vllm:' + metric + r'(?:\{[^}]*\})?\s+([0-9.eE+-]+)', text, re.MULTILINE)
        result[metric] = sum(float(value) for value in values) if values else None
    return result


def observed_turn_timings(start):
    result = subprocess.run(['docker', 'logs', '--since', str(start), NAME], capture_output=True, text=True)
    rows = []
    for line in (result.stdout + result.stderr).splitlines():
        match = re.search(r'推荐轮次耗时 route=(\w+) success=(true|false) stages=\{([^}]+)\}', line)
        if match:
            times = {key: float(value) for key, value in re.findall(r'([\w]+_ms)=([0-9.eE+-]+)', match.group(3))}
            rows.append({'route': match.group(1), 'success': match.group(2) == 'true', 'stages': times})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('name')
    parser.add_argument('--levels', default='2,4,8,16,24,32')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--continue-after-failure', action='store_true')
    args = parser.parse_args()
    assert re.fullmatch('[a-z0-9-]+', args.name)
    levels = [int(value) for value in args.levels.split(',')]
    assert all(1 <= value <= 32 for value in levels)
    source = inspect(NAME)
    env = dict(item.split('=', 1) for item in source['Config']['Env'] if '=' in item)
    assert all(env[key] == value for key, value in PARAMETERS.items())
    deployment = json.loads((ROOT / 'deployment.json').read_text())
    assert deployment['deployed'] and source['Id'] == deployment['new_container_id']
    spec = importlib.util.spec_from_file_location('business_probe', '/tmp/rs-agent-quantization-retry-20261011/business_probe.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    assert probe.BASE == 'http://127.0.0.1:18288'
    users = probe.accounts()
    report = {'name': args.name, 'agent_sha256': SHA, 'model_before': identity(),
        'scope': '现有网关 18288 → 已升级单活 Agent 18214 → 真实模型/推荐/目录/持久历史',
        'queries': list(QUERIES), 'stages': [], 'quality_scope': '完整流程属性与工具状态，不替代语义质量评测',
        'timing_scope': 'Session 预先创建；请求计时包含网关/SSE/目录，整批吞吐包含后置历史及追踪核验'}
    destination = ROOT / (args.name + '.json')
    def save():
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    save()

    def sample(index, session, query, label):
        entry = {'index': index, 'query_index': QUERIES.index(query) if query in QUERIES else None}
        started = time.perf_counter()
        try:
            row = probe.one(users[index % len(users)], query, 'fast', label, session)
            final = row.get('response') or {}
            ids = [item['item_id'] for item in final.get('recommended_items', [])]
            history = row.get('history', {}).get('turns', [])
            trace = row.get('recommend_trace') or {}
            request = urllib.request.Request('http://127.0.0.1:18214/api/platform/agent/' + session + '/turns',
                                            headers={'X-User-Roles': 'OBSERVER'})
            with urllib.request.urlopen(request, timeout=15) as response:
                turns = json.load(response).get('turns', [])
            tools = turns[-1].get('tool_calls', []) if turns else []
            tool_names = [tool.get('tool_name') for tool in tools]
            failed_tools = sum(tool.get('status') in ('FAILED', 'ERROR', 'UNAVAILABLE') for tool in tools)
            entry.update(complete_ms=row.get('complete_with_catalog_ms'), agent_ms=row['agent_done_ms'], items=len(ids),
                answer_chars=len(final.get('assistant_message', '')), finish_reason=history[-1].get('finish_reason') if history else None,
                error_code=(row.get('error') or {}).get('error_code', (row.get('error') or {}).get('code')),
                error_status=(row.get('error') or {}).get('status'), tool_names=tool_names, failed_tools=failed_tools,
                advanced_tool_count=sum(name not in ('recommend_candidates', 'emit_final_answer') for name in tool_names),
                stage_counts=trace.get('stage_counts'), degradation_reasons=final.get('degradation_reasons'),
                history_turns=len(history), final_blocks=[block.get('type') for block in final.get('answer_blocks', [])])
            checks = {'complete': bool(final) and not row.get('error'),
                'five_real_unique_items': len(ids) == len(set(ids)) == len(row.get('catalog', [])) == 5,
                'answer_and_history': entry['answer_chars'] > 0 and entry['finish_reason'] == 'FINAL_ANSWER',
                'tools_without_failure': failed_tools == 0,
                'deepfm_bge': trace.get('stage_counts', {}).get('deepfm_scored', 0) > 0
                    and trace.get('stage_counts', {}).get('bge_reranked', 0) > 0,
                'no_degradation': final.get('degradation_reasons') == [] and trace.get('config', {}).get('ranking_degraded') == 0}
            entry.update(checks=checks, passed=all(checks.values()))
        except Exception as error:
            entry.update(passed=False, error_type=type(error).__name__,
                         http_status=error.code if isinstance(error, urllib.error.HTTPError) else None)
        entry['audit_wall_ms'] = round((time.perf_counter() - started) * 1000, 2)
        return entry

    def new_session(index):
        return probe.http('/api/sessions', {'entryScene': 'complex-concurrency-live'},
                          users[index % len(users)]['accessToken'])['sessionId']

    if args.smoke:
        cases = []
        for index, query in enumerate(('推荐鼠标', QUERIES[0], QUERIES[1], '请帮我推荐鼠标', '换一批鼠标，适合办公使用')):
            if index != 4:
                session = new_session(index)
            account_index = 3 if index == 4 else index
            cases.append(sample(account_index, session, query, args.name + '-' + str(index)))
            save()
        assert cases[-1].get('history_turns') == 2, '多轮历史未保留'
        report['cases'] = cases
        report['passed'] = sum(case['passed'] for case in cases)
        save()
        print('切换后功能验收', report['passed'], '/ 5', flush=True)
    else:
        report['warmup'] = [sample(index, new_session(index), query, args.name + '-warm-' + str(index))
                            for index, query in enumerate(QUERIES)]
        save()
        assert all(row['passed'] for row in report['warmup']), '复杂单请求未通过，停止阶梯'
        for count in levels:
            sessions = [new_session(index) for index in range(count)]
            dependencies_before = dependency_snapshot()
            barrier = threading.Barrier(count)
            stop = threading.Event()
            metrics = []
            before = model_metrics()
            def monitor():
                while not stop.wait(0.2):
                    try:
                        metrics.append(model_metrics())
                    except OSError:
                        pass
            def run(index):
                barrier.wait(timeout=10)
                return sample(index, sessions[index], QUERIES[index % len(QUERIES)],
                              args.name + '-c' + str(count) + '-' + str(index))
            watcher = threading.Thread(target=monitor, daemon=True)
            watcher.start()
            start_epoch = time.time()
            begin = time.perf_counter()
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=count) as workers:
                    rows = list(workers.map(run, range(count)))
            finally:
                elapsed = time.perf_counter() - begin
                stop.set()
                watcher.join(5)
            after = model_metrics()
            latencies = [row['complete_ms'] for row in rows if row['passed']]
            timings = observed_turn_timings(start_epoch)
            stage = {'concurrent_requests': count, 'distinct_accounts': min(count, len(users)),
                'distinct_sessions': len(set(sessions)), 'passed': len(latencies), 'failed': count - len(latencies),
                'batch_wall_ms': round(elapsed * 1000, 2), 'completed_requests_per_second': round(len(latencies) / elapsed, 3),
                'median_ms': round(statistics.median(latencies), 2) if latencies else None,
                'maximum_ms': max(latencies) if latencies else None,
                'peak_model_running': max((row['num_requests_running'] or 0 for row in metrics), default=None),
                'peak_model_waiting': max((row['num_requests_waiting'] or 0 for row in metrics), default=None),
                'preemptions_delta': after['num_preemptions_total'] - before['num_preemptions_total'],
                'complex_tool_cases': sum(row.get('advanced_tool_count', 0) > 0 for row in rows),
                'cases': rows, 'server_turn_timings': timings,
                'start_epoch': start_epoch, 'dependencies_before': dependencies_before,
                'dependencies_after': dependency_snapshot(),
                'timing_note': '服务日志/模型指标是共享时间窗口数据，可能含其他用户请求；不是逐请求精准关联'}
            stage['dependencies_stable'] = stage['dependencies_before'] == stage['dependencies_after']
            report['stages'].append(stage)
            save()
            print('复杂并发', count, '完整通过', len(latencies), '/', count,
                  '中位耗时', stage['median_ms'], 'ms；吞吐', stage['completed_requests_per_second'], '/s', flush=True)
            if stage['failed'] and not args.continue_after_failure:
                report['stopped_at_first_failure'] = count
                save()
                break
    report['model_after'] = identity()
    report['model_process_unchanged'] = report['model_before'] == report['model_after']
    report['agent_container_unchanged'] = inspect(NAME)['Id'] == deployment['new_container_id']
    save()


if __name__ == '__main__':
    main()
