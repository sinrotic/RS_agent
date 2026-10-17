"""核验空闲 GPU 1 模型，备份部署文件后恢复 16K Agent 上下文配置。"""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
import urllib.request


DEPLOY = Path('/home/luo/RS_agent_java/model_deploy')
ROOT = Path('/tmp/rs-agent-e2e-20261010-storage-opt')
RECORD = DEPLOY / 'context-optimization-20261010'


def command(pid):
    path = Path(f'/proc/{pid}/cmdline')
    return path.read_bytes().decode().split('\0')[:-1] if path.exists() else []


def apply():
    candidates = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit(): continue
        try:
            args = command(proc.name)
            if 'serve' in args and '--served-model-name' in args and 'qwen35-4b' in args and '--port' in args and args[args.index('--port') + 1] == '18082':
                candidates.append((int(proc.name), args))
        except (FileNotFoundError, PermissionError): pass
    assert len(candidates) == 1, '模型进程必须唯一'
    pid, args = candidates[0]
    environment = dict(value.split('=', 1) for value in Path(f'/proc/{pid}/environ').read_bytes().decode().split('\0') if '=' in value)
    assert environment.get('CUDA_VISIBLE_DEVICES') == '1', '只允许 GPU 1'
    parent = int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[1])
    expected = command(parent)
    assert expected == ['bash', str(DEPLOY / 'start_qwen35_4b_vllm.sh')]
    with urllib.request.urlopen('http://127.0.0.1:18082/metrics', timeout=5) as response:
        for line in response.read().decode().splitlines():
            if line.startswith(('vllm:num_requests_running{', 'vllm:num_requests_waiting{')):
                assert float(line.rsplit(None, 1)[1]) == 0, '模型仍有请求'
    RECORD.mkdir(mode=0o700)
    for name in ('.env', 'start_qwen35_4b_vllm.sh'):
        shutil.copy2(DEPLOY / name, RECORD / name)
        (RECORD / name).chmod(0o600)
    summary = {'original_pid': pid, 'original_wrapper': parent, 'original_command': args,
               'gpu': 1, 'max_model_len': 16384, 'gpu_memory_utilization': 0.78}
    # 保存足够的配置以供回退，过滤其他凭证。
    saved = {key: value for key, value in environment.items() if key.startswith('VLLM_') or key in
             ('CUDA_VISIBLE_DEVICES', 'MODEL_PATH', 'SERVED_MODEL_NAME', 'AGENT_SYSTEM_PROMPT_FILE', 'AGENT_SYSTEM_PROMPT_URL')}
    (RECORD / 'environment.private.json').write_text(json.dumps(saved)); (RECORD / 'environment.private.json').chmod(0o600)
    assert command(parent) == expected
    os.kill(parent, signal.SIGTERM)
    for _ in range(90):
        if not command(pid): break
        time.sleep(1)
    else: raise RuntimeError('原模型未退出，拒绝启动第二个实例')
    time.sleep(3)
    source = (ROOT / 'start_qwen35_4b_vllm.sh').read_text()
    (DEPLOY / 'start_qwen35_4b_vllm.sh').write_text(source); (DEPLOY / 'start_qwen35_4b_vllm.sh').chmod(0o755)
    content = (DEPLOY / '.env').read_text()
    for key, value in {'CUDA_VISIBLE_DEVICES':'1', 'VLLM_MAX_MODEL_LEN':'16384', 'VLLM_GPU_MEMORY_UTILIZATION':'0.78'}.items():
        pattern = rf'(?m)^{key}=.*$'
        content = re.sub(pattern, key + '=' + value, content) if re.search(pattern, content) else content.rstrip() + '\n' + key + '=' + value + '\n'
    (DEPLOY / '.env').write_text(content); (DEPLOY / '.env').chmod(0o600)
    launch_env = dict(os.environ)
    launch_env.update(saved)
    launch_env.update(CUDA_VISIBLE_DEVICES='1', VLLM_MAX_MODEL_LEN='16384', VLLM_GPU_MEMORY_UTILIZATION='0.78')
    with (RECORD / 'model.log').open('wb') as log:
        process = subprocess.Popen(['bash', str(DEPLOY / 'run_qwen35_4b_vllm.sh')], env=launch_env,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    summary['wrapper_pid'] = process.pid
    (RECORD / 'result.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__': apply()
