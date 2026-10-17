"""只读采集当前公开服务状态；不输出账号、环境变量或原始业务日志。"""
import datetime
import json
import re
import subprocess
import urllib.error
import urllib.request
from collections import Counter

from deploy_live import ROOT, NAME, identity, inspect


def main():
    report = {'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'models_now': identity(), 'containers': {}, 'health': {}}
    for name in (NAME, 'rs-e2e-857e8b14-recommend-fast', 'rs-e2e-857e8b14-model',
                 'rs-e2e-857e8b14-gateway', 'rs-e2e-857e8b14-catalog'):
        try:
            row = inspect(name)
            report['containers'][name] = {'id': row['Id'], 'running': row['State']['Running'],
                'status': row['State']['Status'], 'started': row['State']['StartedAt'],
                'finished': row['State']['FinishedAt'], 'exit_code': row['State']['ExitCode']}
        except subprocess.CalledProcessError:
            report['containers'][name] = {'present': False}
    for name, port, path in (('agent', 18214, '/actuator/health'), ('gateway', 18288, '/actuator/health'),
            ('recommend', 18213, '/actuator/health'), ('catalog', 18202, '/actuator/health'),
            ('user', 18201, '/actuator/health'), ('frontend', 18289, '/'), ('model', 18082, '/health')):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=5) as response:
                report['health'][name] = {'port': port, 'http_status': response.status}
        except urllib.error.HTTPError as error:
            report['health'][name] = {'port': port, 'http_status': error.code}
        except urllib.error.URLError as error:
            report['health'][name] = {'port': port, 'error_type': type(error.reason).__name__}
    logs = subprocess.run(['docker', 'logs', '--since', '5m', '--tail', '250', NAME],
                          capture_output=True, text=True)
    raw = logs.stdout + logs.stderr
    report['recent_agent_exception_types'] = dict(Counter(re.findall(r'\b([A-Z][A-Za-z]+Exception)\b', raw)))
    report['recent_agent_connection_refused_count'] = len(re.findall('Connection refused', raw, re.I))
    report['recent_agent_refused_ports'] = sorted(set(re.findall(r'Connection refused[^\n]*?:(\d{4,5})', raw, re.I)))
    destination = ROOT / 'status-check.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
