"""量化后共享服务小样本复测；不重启或修改服务，只公开性能与验收计数。"""
import hashlib
import json
import re
import subprocess
import time
import urllib.request
from datetime import datetime, timezone

from probe import ROOT, accounts, one

OUTPUT = ROOT / 'quantized-current-check.json'


def model_state():
    processes = subprocess.check_output(['pgrep', '-af', 'vllm serve'], text=True)
    commands = [line for line in processes.splitlines() if '/bin/vllm serve ' in line]
    with urllib.request.urlopen('http://127.0.0.1:18082/v1/models', timeout=5) as response:
        models = json.load(response)
    return {'commands': commands, 'models': models}


def success_count():
    with urllib.request.urlopen('http://127.0.0.1:18082/metrics', timeout=5) as response:
        metrics = response.read().decode()
    return sum(float(value) for value in re.findall(
        r'^vllm:request_success_total(?:\{[^}]*\})?\s+([0-9.eE+-]+)', metrics, re.MULTILINE))


def save(report):
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    OUTPUT.chmod(0o644)


report = {'started_at_utc': datetime.now(timezone.utc).isoformat(),
          'scope': '共享 QA 网关到真实 LLM 推荐结束及目录补齐；会话建立不计入耗时',
          'comparison_limit': '历史 BF16 小样本，非同时控制组；共享服务可能有其他请求',
          'cases': [], 'failures': []}
save(report)
assert (ROOT / 'accounts.json').is_file(), '仅复用已有测试账号'
state = json.loads((ROOT / 'state.json').read_text())
config = json.loads(subprocess.check_output(['docker', 'inspect', state['agent-fast']], text=True))[0]
env = dict(entry.split('=', 1) for entry in config['Config']['Env'] if '=' in entry)
assert env['RS_AGENT_OPENAI_BASE_URL'] == 'http://127.0.0.1:18082/v1'
assert env['RS_AGENT_DIRECT_RECOMMENDATION_ENABLED'] == 'false'
assert env['RS_AGENT_LLM_SYNTHESIS_ENABLED'] == 'true'
report['agent_flags'] = {'direct_recommendation': False, 'llm_synthesis': True}
jar_mounts = [m['Source'] for m in config['Mounts'] if m['Source'].endswith('.jar')]
report['agent_jar_sha256'] = [hashlib.file_digest(open(path, 'rb'), 'sha256').hexdigest() for path in jar_mounts]
save(report)
deadline = time.monotonic() + 180
while True:
    try:
        initial = model_state()
        assert 'INT4-MLP-BF16-sensitive-20261011' in initial['models']['data'][0]['root']
        report['model_before'] = initial
        break
    except (OSError, AssertionError):
        if time.monotonic() >= deadline:
            report['status'] = '模型未就绪，未发送推荐请求'
            save(report)
            raise SystemExit(2)
        print('模型加载尚未就绪，等待现有启动完成', flush=True)
        time.sleep(5)
save(report)
users = accounts()
queries = ('推荐鼠标', '推荐鼠标', '推荐一款适合办公的鼠标，最好静音，说明理由',
           '推荐适合编程使用的键盘，说明各自的区别')
for index, query in enumerate(queries):
    case = {'index': index, 'query': query}
    try:
        before = success_count()
        row = one(users[0], query, 'fast', 'quantized-current-' + str(index))
        result = row.get('response') or {}
        trace = row.get('recommend_trace') or {}
        ids = [item['item_id'] for item in result.get('recommended_items', [])]
        history = row.get('history', {}).get('turns', [])
        case.update(agent_done_ms=row['agent_done_ms'],
                    complete_with_catalog_ms=row.get('complete_with_catalog_ms'),
                    item_count=len(ids), catalog_count=len(row.get('catalog', [])),
                    answer_chars=len(result.get('assistant_message', '')),
                    finish_reason=history[-1].get('finish_reason') if history else None,
                    degradation_reasons=result.get('degradation_reasons'),
                    stage_counts=trace.get('stage_counts'),
                    ranking_degraded=trace.get('config', {}).get('ranking_degraded'),
                    model_success_counter_delta=success_count() - before)
        checks = {'response_without_error': bool(result) and not row.get('error'),
                  'five_unique_catalog_items': len(ids) == len(set(ids)) == len(row.get('catalog', [])) == 5,
                  'answer_text': case['answer_chars'] > 0,
                  'final_answer': case['finish_reason'] == 'FINAL_ANSWER',
                  'no_declared_degradation': result.get('degradation_reasons') == [],
                  'real_deepfm_bge': trace.get('stage_counts', {}).get('deepfm_scored', 0) > 0
                      and trace.get('stage_counts', {}).get('bge_reranked', 0) > 0,
                  'ranking_not_degraded': case['ranking_degraded'] == 0,
                  'model_activity_observed': case['model_success_counter_delta'] >= 1}
        case['checks'] = checks
        case['passed'] = all(checks.values())
    except Exception as error:
        # 不输出 HTTP 正文或响应，避免在异常分支公开原始业务数据。
        case.update(passed=False, error_type=type(error).__name__)
    report['cases'].append(case)
    if not case['passed']:
        report['failures'].append(index)
    save(report)
    print('复测', index, '完成', case.get('complete_with_catalog_ms'), 'ms；验收', case['passed'], flush=True)
report['model_after'] = model_state()
report['model_process_unchanged'] = (
    report['model_before']['commands'] == report['model_after']['commands']
    and report['model_before']['models']['data'][0]['root'] == report['model_after']['models']['data'][0]['root']
    and report['model_before']['models']['data'][0]['max_model_len'] == report['model_after']['models']['data'][0]['max_model_len'])
report['status'] = '完成'
save(report)
print('复测结束；失败数', len(report['failures']), '；模型进程保持一致', report['model_process_unchanged'], flush=True)
