"""只读诊断共享依赖及测试夹具追踪接口，不输出身份或响应正文。"""
import importlib.util
import json
import subprocess
import urllib.error
import urllib.request

from deploy_live import ROOT, NAME, identity, inspect


def main():
    report = {'models_now': identity(), 'services': [], 'trace_checks': [], 'failed_tool_codes': []}
    for name in (NAME, 'rs-e2e-857e8b14-recommend-fast', 'rs-e2e-857e8b14-model',
                 'rs-e2e-857e8b14-gateway', 'rs-e2e-857e8b14-catalog'):
        container = inspect(name)
        report['services'].append({'name': name, 'id': container['Id'], 'started': container['State']['StartedAt']})
    (ROOT / 'dependencies-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    spec = importlib.util.spec_from_file_location('business_probe', '/tmp/rs-agent-quantization-retry-20261011/business_probe.py')
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    users = json.loads((probe.ROOT / 'accounts.json').read_text())
    for index in range(2):
        account = users[index]
        sessions = probe.http('/api/sessions?entryScene=complex-concurrency-live&limit=1', token=account['accessToken'])
        session = sessions[0]['sessionId']
        request = urllib.request.Request('http://127.0.0.1:18214/api/platform/agent/' + session + '/turns',
                                        headers={'X-User-Roles': 'OBSERVER'})
        with urllib.request.urlopen(request, timeout=10) as response:
            turn = json.load(response)['turns'][-1]
        for tool in turn.get('tool_calls', []):
            if tool.get('status') == 'FAILED':
                metadata = tool.get('metadata') or {}
                report['failed_tool_codes'].append({'account_index': index, 'name': tool.get('tool_name'),
                    'code': metadata.get('error_code'), 'metadata_keys': list(metadata)})
        card = turn.get('card_set_id')
        report['trace_checks'].append({'account_index': index, 'card_id_length': len(card or '')})
        for roles in (None, 'OBSERVER'):
            headers = {} if roles is None else {'X-User-Roles': roles}
            request = urllib.request.Request('http://127.0.0.1:18213/api/platform/recommend/' + card + '/trace', headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    raw = response.read()
                    data = json.loads(raw) if raw else {}
                    report['trace_checks'].append({'account_index': index, 'roles': roles, 'status': response.status,
                        'body_bytes': len(raw), 'keys': list(data), 'stage_counts': data.get('stage_counts'),
                        'ranking_degraded': data.get('config', {}).get('ranking_degraded')})
            except urllib.error.HTTPError as error:
                report['trace_checks'].append({'account_index': index, 'roles': roles, 'status': error.code})
    (ROOT / 'dependencies-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
