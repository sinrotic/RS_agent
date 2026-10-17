"""创建全新验收环境，保留所有业务依赖，仅使用隔离的可写数据。"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ROOT = '/tmp/rs-agent-e2e-20261010-storage-opt'
OLD = '/tmp/rs-agent-e2e-20261010-profile-1600'
PREVIOUS = HERE.parent / 'agent-latency-profile-20261010'


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, encoding='utf-8', **kwargs)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    bootstrap = f"""from pathlib import Path
import shutil
root=Path({ROOT!r});old=Path({OLD!r})
assert not root.exists(), '验收目录已存在，拒绝复用'
root.mkdir()
for file in old.iterdir():
    if file.suffix in ('.sql','.cql') or file.name in ('bge_m3_embedding_server.py','latency-agent-v2.jar') or (file.suffix=='.jar' and file.name not in ('rs-service-agent.jar','rs-service-recommend.jar')):
        shutil.copy2(file,root/file.name)
"""
    run(['ssh', 'server', 'python3 -'], input=bootstrap)
    for name in ('environment.py', 'probe.py', 'measure.py', 'start_bge.py', 'stop_bge.py', 'restart_services.py'):
        source = (PREVIOUS / name).read_text(encoding='utf-8').replace(OLD, ROOT)
        if name == 'environment.py':
            # 不再使用独立 NVMe 对照实例；验收正式迁移后的 MySQL 13306。
            source = source.replace('jdbc_port = 18306 if label in ("agent-fast", "recommend-fast", "user") and os.environ.get("RS_PROFILE_STORAGE") == "nvme" else 13306', 'jdbc_port = 13306')
        (HERE / name).write_text(source, encoding='utf-8')
    sources = [HERE / name for name in ('environment.py','probe.py','measure.py','start_bge.py','stop_bge.py','restart_services.py','deploy_context.py')]
    sources.append(REPO / 'java_agent/deploy/remote/model/start_qwen35_4b_vllm.sh')
    for file in sources:
        run(['scp',str(file),'server:'+ROOT+'/'+file.name])
    print('已创建隔离验收目录并上传工具', flush=True)
