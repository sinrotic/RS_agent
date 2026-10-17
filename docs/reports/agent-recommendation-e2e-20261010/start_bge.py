"""仅启动独立端口的 GPU 1 验收模型，记录 PID 供清理。"""
import json
import os
import subprocess
from pathlib import Path

root = Path('/tmp/rs-agent-e2e-20261010-1247')
env = dict(os.environ, CUDA_VISIBLE_DEVICES='1', HF_HUB_OFFLINE='1',
           TRANSFORMERS_OFFLINE='1', OMP_NUM_THREADS='4', MKL_NUM_THREADS='4')
command = ['/home/luo/RS_agent_remote/.venv/bin/python', str(root / 'bge_m3_embedding_server.py'),
           '--model-path', '/home/luo/RS_agent_java/data/models/BAAI/bge-m3',
           '--reranker-path', '/home/luo/RS_agent_java/data/models/BAAI/bge-reranker-v2-m3',
           '--host', '127.0.0.1', '--port', '18215', '--device', 'cuda', '--dtype', 'float16',
           '--rerank-batch-size', '64', '--gpu-memory-fraction', '0.11']
with (root / 'bge.log').open('wb') as log:
    process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                               start_new_session=True)
(root / 'bge-pid.json').write_text(json.dumps({'pid': process.pid, 'command': command}))
print('BGE PID', process.pid)
