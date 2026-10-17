"""保留过期令牌拒绝记录，登录相同测试账号后重新运行。"""
import json
from pathlib import Path
import subprocess
import shutil

ROOT = Path('/tmp/rs-agent-e2e-20261010-storage-opt')
for name in ('optimized-final', 'ordinary-final'):
    evidence = ROOT / (name + '.json')
    preserved = ROOT / (name.replace('-final', '-expired-token') + '.json')
    if not evidence.exists(): evidence = preserved
    rows = json.loads(evidence.read_text())
    assert rows['failures'] and all('HTTP 401:' in row['error'] for row in rows['failures'])
    for extension in ('.json', '.log'):
        source = ROOT / (name + extension)
        target = ROOT / (name.replace('-final', '-expired-token') + extension)
        if target.exists(): continue
        if source.exists(): shutil.copy2(source, target)
for command, log in ((['python3', str(ROOT / 'measure.py'), 'optimized-final', '--cold-variants'], 'optimized-final.log'),
                     (['python3', str(ROOT / 'ordinary.py'), 'ordinary-final'], 'ordinary-final.log')):
    with (ROOT / log).open('w') as output:
        subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, check=True)
    print(log + ' 完成', flush=True)
