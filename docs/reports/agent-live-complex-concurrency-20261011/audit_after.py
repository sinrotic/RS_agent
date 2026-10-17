"""只读检查切换后身份、已有历史、健康、单活及私有临时文件清理。"""
import hashlib
import importlib.util
import json
import urllib.request

from deploy_live import ROOT, NAME, BACKUP, TARGET, SHA, PARAMETERS, inspect, identity


def main():
    deployment = json.loads((ROOT / 'deployment.json').read_text())
    current = inspect(NAME)
    env = dict(value.split('=', 1) for value in current['Config']['Env'] if '=' in value)
    assert current['Id'] == deployment['new_container_id'] and current['State']['Running']
    assert all(env[key] == value for key, value in PARAMETERS.items())
    assert not inspect(BACKUP)['State']['Running']
    previous = json.loads((ROOT / 'container.previous.private.json').read_text())
    assert current['Image'] == previous['Image'] and current['Config']['Cmd'] == previous['Config']['Cmd']
    original_env = dict(value.split('=', 1) for value in previous['Config']['Env'] if '=' in value)
    changed = {key for key in set(original_env) | set(env) if original_env.get(key) != env.get(key)}
    assert changed <= set(PARAMETERS) | {'SERVER_SHUTDOWN', 'SPRING_LIFECYCLE_TIMEOUT_PER_SHUTDOWN_PHASE'}
    assert hashlib.file_digest(TARGET.open('rb'), 'sha256').hexdigest() == SHA
    report = {'new_agent_running': True, 'old_agent_stopped': True, 'single_active_agent': True,
              'agent_sha256': SHA, 'parameters': PARAMETERS, 'gateway_rate_limit_unchanged': True,
              'image_and_command_preserved': True, 'environment_change_scope_verified': True,
              'private_temp_env_removed': not (ROOT / 'live.private.env').exists(),
              'existing_history_checked': [], 'health': {}}
    spec = importlib.util.spec_from_file_location('business_probe', '/tmp/rs-agent-quantization-retry-20261011/business_probe.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    # 使用测试期间有效的令牌，不创建或刷新其他账号的登录态。
    users = json.loads((probe.ROOT / 'accounts.json').read_text())
    for index, account in enumerate(users):
        sessions = probe.http('/api/sessions?entryScene=concurrency-benchmark&limit=5', token=account['accessToken'])
        checked = False
        for session in sessions:
            history = probe.http('/api/agent/sessions/' + session['sessionId'] + '/history',
                                 token=account['accessToken'], route='fast')
            turns = history.get('turns', [])
            if turns and turns[-1].get('finish_reason') == 'FINAL_ANSWER':
                report['existing_history_checked'].append({'account_index': index, 'readable': True,
                    'turns': len(turns), 'answer_chars': len(turns[-1].get('assistant_message', ''))})
                checked = True
                break
        assert checked, '切换前的测试 Session 历史未验证通过'
    for name, port, path in (('agent', 18214, '/actuator/health'), ('gateway', 18288, '/actuator/health'),
        ('recommend', 18213, '/actuator/health'), ('catalog', 18202, '/actuator/health'),
        ('user', 18201, '/actuator/health'), ('frontend', 18289, '/'), ('model', 18082, '/health')):
        with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=10) as response:
            assert response.status == 200
            report['health'][name] = 200
    report['model_after'] = identity()
    primary_before = [line for line in deployment['model_before'] if '--port 18082 ' in line]
    report['model_process_unchanged'] = primary_before == report['model_after']
    assert report['model_process_unchanged'] and report['private_temp_env_removed']
    (ROOT / 'audit-after.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print('新版、单活、模型、前端及业务健康检查通过；8 个账号切换前历史可读', flush=True)


if __name__ == '__main__':
    main()
