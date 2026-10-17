"""只重启当前 state 登记的四个 QA 服务，切换计时探针；业务构建不变。"""
import argparse
import json
import os
import subprocess
from probe import ROOT

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=('control', 'profile'))
parser.add_argument('--storage', choices=('hdd', 'nvme'), default='hdd')
args = parser.parse_args()
state_path = ROOT / 'state.json'
state = json.loads(state_path.read_text())
assert not state.get('cleaned')
prefix = 'rs-e2e-' + state['suffix'] + '-'
for label in ('agent-fast', 'recommend-fast', 'user', 'model'):
    name = state.get(label)
    if not name: continue
    assert name == prefix + label and name in state['containers']
    subprocess.run(['docker', 'rm', '-f', name], check=True, capture_output=True)
    state['containers'].remove(name); del state[label]
    state_path.write_text(json.dumps(state, indent=2))
environment = dict(os.environ, RS_PROFILE_ENABLED='true' if args.mode == 'profile' else 'false',
                   RS_PROFILE_STORAGE=args.storage)
subprocess.run(['python3', str(ROOT / 'environment.py'), 'services', '--root', str(ROOT)],
               env=environment, check=True)
print('QA 模式切换', args.mode, flush=True)
