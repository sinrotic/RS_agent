"""GPU 2 隔离量化对照；只关闭本进程创建的模型，不触碰正式实例。"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / 'model'
IGNORE = ['lm_head', 're:.*visual.*', 're:.*linear_attn.*', 're:.*self_attn.*']
EDGES = list(range(8)) + list(range(24, 32))
VARIANTS = {
    'bf16': None,
    'w8a16_middle': {'ignore': IGNORE + ['re:.*layers\\.(?:' + '|'.join(map(str, EDGES)) + ')\\..*']},
    'w8a16_middle8': {'ignore': IGNORE + ['re:.*layers\\.(?:' + '|'.join(map(str, list(range(8)) + list(range(16, 32)))) + ')\\..*']},
    'w8a16_mlp': {'ignore': IGNORE},
    'int4_autoround': None,
}


def gpu_memory():
    return int(subprocess.check_output(['nvidia-smi', '-i', '2', '--query-gpu=memory.used',
                                       '--format=csv,noheader,nounits'], text=True).strip())


def stop_owned(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=15)
    for _ in range(30):
        if gpu_memory() < 512:
            return
        time.sleep(1)
    raise RuntimeError('本次进程关闭后 GPU 2 仍占用，停止后续实验，不清理其他进程')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--variant', choices=list(VARIANTS), required=True)
    parser.add_argument('--repeat', type=int, default=1, choices=[1, 2])
    parser.add_argument('--business-only', action='store_true')
    parser.add_argument('--model-only', action='store_true')
    parser.add_argument('--gpu-memory-utilization', choices=['0.78', '0.50'], default='0.78')
    args = parser.parse_args()
    assert not (args.business_only and args.model_only)
    lock = open('/tmp/rs-serving-tuning-gpu2.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    label = args.variant + (f'_restart{args.repeat}' if args.repeat > 1 else '')
    if args.gpu_memory_utilization != '0.78':
        label += '_memory50'
    deadline = time.monotonic() + 180
    while gpu_memory() >= 512 and time.monotonic() < deadline:
        time.sleep(2)
    if gpu_memory() >= 512:
        raise RuntimeError('GPU 2 持续使用中，未启动对照模型')
    with socket.socket() as connection:
        assert connection.connect_ex(('127.0.0.1',18092)) != 0, '测试端口正在使用'
    config = VARIANTS[args.variant]
    model_path = '/mnt/data/luo/models/Qwen3.5-4B'
    cache_family = args.variant
    if args.variant == 'int4_autoround':
        manifest = 'int4-runtime-source.json' if args.repeat == 2 else 'int4-source.json'
        source = json.loads((ROOT / manifest).read_text())
        assert source['revision'] == '0a857215cab37e8caa857a053005a73cf98ff2c4'
        model_path = source['path']
        if args.repeat == 2:
            assert source['effective_tokenizer_identical'] and not source['weights_changed']
    ready = ROOT / (label + '.ready')
    ready.unlink(missing_ok=True)
    env = {**os.environ, 'CUDA_VISIBLE_DEVICES':'2', 'VLLM_PORT':'18092',
           'MODEL_PATH':model_path, 'VLLM_MAX_MODEL_LEN':'16384',
           'VLLM_GPU_MEMORY_UTILIZATION':args.gpu_memory_utilization, 'VLLM_JSON_COMPACT_OUTPUT':'true',
           'VLLM_QUANTIZATION':'fp8_per_block' if config else 'auto',
           'VLLM_QUANTIZATION_CONFIG':json.dumps(config,separators=(',',':')) if config else '',
           'VLLM_TEST_FORCE_FP8_MARLIN':'1' if config else '0',
           'VLLM_SPECULATIVE_CONFIG':'', 'VLLM_LANGUAGE_MODEL_ONLY':'false',
           'VLLM_MAX_NUM_SEQS':'', 'VLLM_MAX_NUM_BATCHED_TOKENS':'',
           'VLLM_CACHE_ROOT':str(ROOT / 'cache' / cache_family),
           'VLLM_READY_FILE':str(ready), 'VLLM_READY_TIMEOUT_SEC':'600',
           'VLLM_PREFIX_KEEPALIVE':'false', 'VLLM_WARMUP_CONCURRENCY':'8',
           'VLLM_WARMUP_PAYLOAD_FILE':str(ROOT / 'replay-payloads.private.json'),
           'VLLM_WARMUP_MAX_TOKENS':'1', 'VLLM_DELAY_AFTER_WARMUP_SEC':'0',
           'VLLM_STRUCTURED_OUTPUT_PROBE':'true', 'VLLM_ENFORCE_STRICT_TOOL_CALLING':'true',
           'PYTHON_BIN':sys.executable}
    state={'variant':args.variant,'repeat':args.repeat,'model_path':model_path,
           'scope':'model_only' if args.model_only else 'business_only' if args.business_only else 'model_and_business',
           'configuration':{k:v for k,v in env.items()
            if k in ('VLLM_QUANTIZATION','VLLM_QUANTIZATION_CONFIG','VLLM_TEST_FORCE_FP8_MARLIN',
                     'VLLM_CACHE_ROOT','VLLM_GPU_MEMORY_UTILIZATION')},'passed':False}
    print('开始隔离对照',label,state['configuration'],flush=True)
    with (ROOT/(label+'.log')).open('w') as log:
        process=subprocess.Popen(['bash',str(MODEL/'start_qwen35_4b_vllm.sh')],cwd=MODEL,env=env,
                    stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        deadline=time.monotonic()+660
        while not ready.exists():
            if process.poll() is not None:
                raise RuntimeError(f'模型启动失败：{label} exit={process.returncode}')
            if time.monotonic()>deadline:
                raise TimeoutError('模型就绪超时')
            time.sleep(2)
        artifact = ROOT / (label+'.json')
        if args.business_only:
            artifact.write_text(json.dumps({'scope':'business_only','variant':args.variant})+'\n')
            subprocess.run([sys.executable,'-c',
                           'from pathlib import Path; import sys; from business import append_business; append_business(Path(sys.argv[1]))',
                           str(artifact)],cwd=ROOT,check=True,timeout=300)
        else:
            benchmark = ROOT / ('model_direct.py' if args.model_only else 'benchmark.py')
            subprocess.run([sys.executable,str(benchmark),'--base-url','http://127.0.0.1:18092/v1',
                           '--output',str(artifact)],check=True,timeout=300)
        state['passed']=True
        state['gpu_memory_mib']=gpu_memory()
        state['probe']=json.loads(Path(str(ready)+'.structured-output.json').read_text())
        print('通过',label,flush=True)
    except Exception as error:
        state['error']=str(error)
        print('未通过',label,str(error),flush=True)
    finally:
        stop_owned(process)
        (ROOT/(label+'-state.json')).write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    if not state['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
