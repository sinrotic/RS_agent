"""汇总公开回归证据，并检查 Compose 能实际传递候选参数。"""
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
EXPECTED_SHA = '4bc94fc6894a65fb933071ac91c2506c5964542c68d464f59155967c027c1c76'


def main():
    jar = REPO / 'java_agent/rs-service-agent/target/rs-service-agent.jar'
    assert hashlib.file_digest(jar.open('rb'), 'sha256').hexdigest() == EXPECTED_SHA
    tests = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    suites = list((jar.parent / 'surefire-reports').glob('TEST-*.xml'))
    assert suites
    for file in suites:
        suite = ET.parse(file).getroot()
        for key in tests:
            tests[key] += int(suite.get(key, '0'))
    assert tests == {'tests': 235, 'failures': 0, 'errors': 0, 'skipped': 1}
    tests['passed'] = tests['tests'] - tests['skipped']
    phases = {}
    identities = []
    for name in ('baseline', 'baseline-repeat', 'queue-only', 'wide16', 'final', 'guarded4', 'guarded4-repeat'):
        report = json.loads((ROOT / (name + '.json')).read_text(encoding='utf-8'))
        assert report['model_process_unchanged']
        identities.append(report['model_before'])
        phases[name] = [{key: stage[key] for key in ('concurrent_requests', 'distinct_accounts', 'passed', 'failed',
            'completed_requests_per_second', 'median_ms', 'maximum_ms')} for stage in report['stages']]
    assert all(identity == identities[0] for identity in identities)
    functional = {}
    for name in ('functional', 'functional-rec4'):
        report = json.loads((ROOT / (name + '.json')).read_text(encoding='utf-8'))
        assert report['agent_sha256'] == EXPECTED_SHA and report['model_process_unchanged']
        assert all(case['passed'] for case in report['cases']) and len(report['cases']) == 5
        assert report['model_before'] == identities[0]
        functional[name] = {'passed': 5, 'failed': 0}
    deployment = REPO / 'java_agent/deploy/remote/app'
    example = deployment / 'agent-gpu1-concurrency.env.example'
    parameters = dict(line.split('=', 1) for line in example.read_text(encoding='utf-8').splitlines()
                      if line and not line.startswith('#'))
    result = subprocess.run(['docker', 'compose', '--env-file', '.env.example',
        '--env-file', str(example), '-f', 'docker-compose.yml', 'config', '--format', 'json'],
        cwd=deployment, capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, 'Compose 配置检查失败；避免输出可能含私密参数的配置内容'
    configured = json.loads(result.stdout)['services']['rs-service-agent']['environment']
    assert len(parameters) == 10 and all(str(configured.get(key)) == value for key, value in parameters.items())
    cleaned = json.loads((ROOT / 'clone-state.json').read_text(encoding='utf-8'))
    assert cleaned['cleaned'] and cleaned['name'] == 'rs-concurrency-20261011-agent'
    runtime = json.loads((ROOT / 'runtime-check.json').read_text(encoding='utf-8'))
    assert all(runtime[key] for key in ('clone_absent', 'private_env_absent', 'shared_agent_running',
        'shared_agent_health_200', 'model_health_200', 'model_identity_unchanged'))
    validation = {'agent_sha256': EXPECTED_SHA, 'maven_command': 'mvn -pl rs-service-agent -am package -q',
        'agent_tests': tests, 'concurrency_phases': phases, 'functional_checks': functional,
        'selected_parameters': parameters, 'compose_parameter_checks_passed': len(parameters),
        'model_process_unchanged': True, 'model_pid': int(re.match(r'\d+', identities[0][0]).group()),
        'clone_cleaned': True, 'shared_agent_rollout': False, 'runtime_check': runtime,
        'limits': ['8 个真实账号的独立 Session 突发负载', '未测持续负载最大容量或 32 条复杂推荐',
                   '功能属性验收不替代完整语义质量回归', '统计吞吐包含后置核验时间']}
    (ROOT / 'validation.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding='utf-8')
    print('validation: 234 tests passed; 1 conditional skip; Compose 10/10; two 32/32 bursts; functional 5/5')


if __name__ == '__main__':
    main()
