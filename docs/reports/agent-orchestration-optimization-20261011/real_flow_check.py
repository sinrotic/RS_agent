"""独立 Agent 验收当前 GPU 1 模型与真实推荐依赖；不修改共享服务。"""
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = 'rs-orchestration-20261011-agent'
SOURCE = 'rs-e2e-857e8b14-agent-fast'
PORT = 18316
REPORT = ROOT / 'real-flow-check.json'
EXPECTED_SHA = '01ca31c3fd82f22822fa55d8faecc0064387000469ffebf9b9b600a7a2166805'


def model_identity():
    command = subprocess.check_output(['pgrep', '-af', 'vllm serve'], text=True)
    return [line for line in command.splitlines() if '/bin/vllm serve ' in line]


def save(report):
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2))


def cleanup():
    state_file = ROOT / 'clone-state.json'
    if not state_file.exists():
        return
    state = json.loads(state_file.read_text())
    assert state['name'] == NAME and state['port'] == PORT
    result = subprocess.run(['docker', 'inspect', NAME], capture_output=True, text=True)
    if result.returncode == 0:
        config = json.loads(result.stdout)[0]
        assert config['Config']['Labels']['rsagent.orchestration-task'] == '20261011'
        subprocess.run(['docker', 'rm', '-f', NAME], check=True, stdout=subprocess.DEVNULL)
    envfile = ROOT / 'clone.private.env'
    envfile.unlink(missing_ok=True)
    state['cleaned'] = True
    state_file.write_text(json.dumps(state, indent=2))
    print('仅清理本次独立验收容器及凭据副本', flush=True)


if '--cleanup' in sys.argv:
    cleanup()
    raise SystemExit()

assert hashlib.file_digest(open(ROOT / 'rs-service-agent.jar', 'rb'), 'sha256').hexdigest() == EXPECTED_SHA
existing = subprocess.run(['docker', 'inspect', NAME], capture_output=True)
assert existing.returncode != 0, '同名实例已经存在，拒绝覆盖'
source = json.loads(subprocess.check_output(['docker', 'inspect', SOURCE], text=True))[0]
env = dict(entry.split('=', 1) for entry in source['Config']['Env'] if '=' in entry)
assert env['RS_AGENT_OPENAI_BASE_URL'] == 'http://127.0.0.1:18082/v1'
assert env['RS_AGENT_DIRECT_RECOMMENDATION_ENABLED'] == 'false'
assert env['RS_AGENT_LLM_SYNTHESIS_ENABLED'] == 'true'
env.update(SERVER_PORT=str(PORT), SERVER_ADDRESS='127.0.0.1')
envfile = ROOT / 'clone.private.env'
envfile.write_text('\n'.join(key + '=' + value for key, value in env.items()) + '\n')
envfile.chmod(0o600)
command = ['docker', 'run', '-d', '--name', NAME, '--network', 'host', '--memory', '3g',
           '--label', 'rsagent.orchestration-task=20261011', '--env-file', str(envfile)]
replacements = 0
for mount in source['Mounts']:
    assert not mount['RW'], '仅允许复用只读挂载'
    origin = mount['Source']
    if origin.endswith('/rs-service-agent.jar'):
        origin = str(ROOT / 'rs-service-agent.jar')
        replacements += 1
    command += ['--mount', 'type=bind,src=' + origin + ',dst=' + mount['Destination'] + ',readonly']
assert replacements == 1
command += [source['Config']['Image']] + source['Config']['Cmd']
(ROOT / 'clone-state.json').write_text(json.dumps({'name': NAME, 'port': PORT, 'agent_sha256': EXPECTED_SHA}))
subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
report = {'model_before': model_identity(), 'agent_sha256': EXPECTED_SHA,
          'scope': '独立 Agent 完整 LLM 推荐与真实目录、历史、DeepFM/BGE；非量化或端到端加速对照',
          'cases': [], 'failures': []}
save(report)
try:
    deadline = time.monotonic() + 90
    while True:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/actuator/health', timeout=3) as response:
                assert json.load(response)['status'] == 'UP'
            break
        except (OSError, AssertionError):
            if time.monotonic() >= deadline:
                raise TimeoutError('独立验收实例未就绪')
            time.sleep(2)
    spec = importlib.util.spec_from_file_location('business_probe', '/tmp/rs-agent-quantization-retry-20261011/business_probe.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    probe.BASE = f'http://127.0.0.1:{PORT}'
    assert (probe.ROOT / 'accounts.json').is_file()
    users = probe.accounts()
    queries = ('推荐鼠标', '推荐一款适合办公的鼠标，最好静音，说明理由',
               '推荐适合编程使用的键盘，说明各自的区别', '请帮我推荐鼠标', '换一批鼠标，适合办公使用')
    session = None
    for index, query in enumerate(queries):
        case = {'index': index, 'query': query}
        try:
            row = probe.one(users[index >= 3], query, 'fast', 'orchestration-' + str(index),
                            session if index >= 3 else None)
            if index >= 3:
                session = row['session_id']
            final = row.get('response') or {}
            ids = [item['item_id'] for item in final.get('recommended_items', [])]
            trace = row.get('recommend_trace') or {}
            request = urllib.request.Request(probe.BASE + '/api/platform/agent/' + row['session_id'] + '/turns',
                                            headers={'X-User-Roles': 'OBSERVER'})
            with urllib.request.urlopen(request, timeout=15) as response:
                turn = json.load(response)['turns'][-1]
            tools = turn.get('tool_calls', turn.get('toolCalls', []))
            case.update(complete_with_catalog_ms=row.get('complete_with_catalog_ms'),
                        item_count=len(ids), answer_chars=len(final.get('assistant_message', '')),
                        finish_reason=row['history']['turns'][-1]['finish_reason'],
                        tool_names=[tool.get('tool_name', tool.get('toolName')) for tool in tools],
                        failed_tools=sum(tool.get('status') in ('FAILED', 'ERROR', 'UNAVAILABLE') for tool in tools),
                        stage_counts=trace.get('stage_counts'), degradation_reasons=final.get('degradation_reasons'))
            checks = {'complete': bool(final) and not row.get('error'),
                      'five_real_unique_items': len(ids) == len(set(ids)) == len(row.get('catalog', [])) == 5,
                      'text_and_history': case['answer_chars'] > 0 and case['finish_reason'] == 'FINAL_ANSWER',
                      'tools_without_failure': case['failed_tools'] == 0,
                      'deepfm_bge': trace.get('stage_counts', {}).get('deepfm_scored', 0) > 0
                            and trace.get('stage_counts', {}).get('bge_reranked', 0) > 0,
                      'no_declared_degradation': final.get('degradation_reasons') == []
                            and trace.get('config', {}).get('ranking_degraded') == 0}
            case['checks'] = checks
            case['passed'] = all(checks.values())
        except Exception as error:
            case.update(passed=False, error_type=type(error).__name__)
        report['cases'].append(case)
        if not case['passed']:
            report['failures'].append(index)
        save(report)
        print('真实流程验收', index, '耗时', case.get('complete_with_catalog_ms'), 'ms；通过', case['passed'], flush=True)
    report['model_after'] = model_identity()
    report['model_process_unchanged'] = report['model_before'] == report['model_after']
    report['quality_scope'] = '基础链路属性与工具状态检查，不替代完整语义质量回归'
    save(report)
finally:
    cleanup()
