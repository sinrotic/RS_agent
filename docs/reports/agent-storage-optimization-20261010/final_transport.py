"""保留故障前的完整证据，再用复用连接的模型网关执行最终验收。"""
import json
from pathlib import Path
import subprocess

ROOT = Path('/tmp/rs-agent-e2e-20261010-storage-opt')
state = json.loads((ROOT / 'state.json').read_text())
assert not state.get('cleaned')
for name in ('optimized-final', 'ordinary-final'):
    for extension in ('.json', '.log'):
        source = ROOT / (name + extension)
        destination = ROOT / (name.replace('-final', '-before-transport') + extension)
        if source.exists():
            assert not destination.exists(), '保留的原始证据已存在'
            source.rename(destination)
original = ROOT / 'rs-service-model.jar'
backup = ROOT / 'rs-service-model-before-transport.jar'
assert not backup.exists()
original.rename(backup)
(ROOT / 'rs-service-model-transport-fixed.jar').rename(original)
subprocess.run(['python3', str(ROOT / 'restart_services.py'), 'control'], check=True)
for command, log in ((['python3', str(ROOT / 'measure.py'), 'optimized-final', '--cold-variants'], 'optimized-final.log'),
                     (['python3', str(ROOT / 'ordinary.py'), 'ordinary-final'], 'ordinary-final.log')):
    with (ROOT / log).open('w') as output:
        subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, check=True)
    print(log + ' 完成', flush=True)
