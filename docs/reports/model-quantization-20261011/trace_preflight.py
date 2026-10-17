"""只检查本次验收实例是否有逐轮计时，不输出其他配置。"""
import json
from pathlib import Path
import subprocess
import urllib.parse

root = Path(__file__).resolve().parent
data = json.loads(subprocess.check_output(['docker', 'inspect', 'rs-quantization-20261011-agent'], text=True))[0]
env = dict(row.split('=', 1) for row in data['Config']['Env'] if '=' in row)
url = urllib.parse.urlsplit(env.get('RS_PLATFORM_TRACE_SERVICE_URL', 'http://rs-service-platform-trace:18108'))
result = {'trace_enabled': env.get('RS_AGENT_TRACE_ENABLED', 'false'),
          'trace_host': url.hostname, 'trace_port': url.port,
          'trace_url': urllib.parse.urlunsplit((url.scheme, url.hostname + (':' + str(url.port) if url.port else ''), url.path, '', ''))}
(root / 'trace-preflight.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
