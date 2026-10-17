"""停止、删除本次登记的 NVMe QA 实例及其自有数据目录。"""
import json
import subprocess
from pathlib import Path
from probe import ROOT

state_path = ROOT / 'state.json'; state = json.loads(state_path.read_text())
name = state['mysql_nvme']; prefix = 'rs-e2e-' + state['suffix'] + '-'
assert name == prefix + 'mysql-nvme' and name in state['containers']
data_dir = Path(state['mysql_nvme_directory']).resolve()
assert data_dir == ROOT.resolve() / 'mysql-nvme' and not Path(state['mysql_nvme_directory']).is_symlink()
inspect = json.loads(subprocess.run(['docker', 'inspect', name], text=True, capture_output=True, check=True).stdout)[0]
mount = next(m for m in inspect['Mounts'] if m['Destination'] == '/var/lib/mysql')
assert Path(mount['Source']).resolve() == data_dir
subprocess.run(['docker', 'stop', '--time', '30', name], capture_output=True, check=True)
subprocess.run(['docker', 'rm', name], capture_output=True, check=True)
# 数据文件属容器 UID；使用同一已核验目录的临时挂载清理，不能跨到上级目录。
subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--memory', '128m', '--entrypoint', 'sh',
    '--mount', f'type=bind,source={data_dir},target=/owned', state['mysql_nvme_image'],
    '-c', 'find /owned -mindepth 1 -delete'], capture_output=True, check=True)
assert not any(data_dir.iterdir()); data_dir.rmdir()
state['containers'].remove(name); del state['mysql_nvme']
state['mysql_nvme_removed'] = True; state_path.write_text(json.dumps(state, indent=2))
(ROOT / 'qa-private-dump.sql').unlink(missing_ok=True)
print('已清理自有 NVMe QA 数据库与临时数据目录', flush=True)
