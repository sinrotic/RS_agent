"""仅 GPU 1 的可恢复 MTP 实验；不修改正式模型配置文件。"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
PRIVATE=ROOT/'private-model-backup'
FILE=ROOT/'model-switch.json'
ORIGINAL=Path('/home/luo/RS_agent_java/model_deploy/start_qwen35_4b_vllm.sh')
mode=sys.argv[1]
assert mode in ('mtp','restore','status')
def command(pid):
    file=Path(f'/proc/{pid}/cmdline')
    return file.read_bytes().decode().split('\0')[:-1] if file.exists() else []
if mode=='status':
    state=json.loads(FILE.read_text())
    print(json.dumps({'mode':state['mode'],'pid':state['pid'], 'running':bool(command(state['pid'])),
                      'ready':Path(state['ready_file']).exists()},ensure_ascii=False)); sys.exit()
if not FILE.exists():
    assert mode=='mtp'
    wrapper=1505258; api=1505267
    assert command(wrapper)==['bash',str(ORIGINAL)]
    assert 'vllm' in ' '.join(command(api)) and '--port' in command(api)
    env=dict(entry.split('=',1) for entry in Path(f'/proc/{api}/environ').read_bytes().decode().split('\0') if '=' in entry)
    assert env.get('CUDA_VISIBLE_DEVICES')=='1'
    assert env.get('VLLM_MAX_MODEL_LEN')=='16384'
    PRIVATE.mkdir(mode=0o700)
    (PRIVATE/'environment.json').write_text(json.dumps(env)); (PRIVATE/'environment.json').chmod(0o600)
    (PRIVATE/'original.sh').write_bytes(ORIGINAL.read_bytes())
    state={'mode':'original','pid':wrapper,'command':command(wrapper),
           'ready_file':env.get('VLLM_READY_FILE','/tmp/rs_agent_latency/vllm_qwen35_4b.ready')}
    (PRIVATE/'original-state.json').write_text(json.dumps(state))
    FILE.write_text(json.dumps(state,indent=2))
else: state=json.loads(FILE.read_text())
subprocess.run(['python3',str(ROOT/'stop_bge.py')],check=True)
pid=state['pid']
if command(pid):
    assert command(pid)==state['command'] and os.getpgid(pid)==pid, 'model PID owner mismatch'
    os.kill(pid,signal.SIGTERM)
    for _ in range(60):
        group=subprocess.run(['ps','-eo','pgid=,args='],text=True,capture_output=True,check=True).stdout
        if not any(line.strip().split(maxsplit=1)[0]==str(pid) and 'defunct' not in line for line in group.splitlines()): break
        time.sleep(.5)
    else: raise RuntimeError('owned model group did not stop; no new model started')
env=json.loads((PRIVATE/'environment.json').read_text())
if mode=='mtp':
    log_file=ROOT/('mtp-retry-model.log' if (ROOT/'mtp-model.log').exists() else 'mtp-model.log')
    assert not log_file.exists(), 'only one cold-start retry is allowed'
    script=ROOT/'mtp-experiment.sh'
    source=(PRIVATE/'original.sh').read_text()
    needle='  --enable-prefix-caching\n'
    assert source.count(needle)==1
    source=source.replace(needle, needle+'  --mamba-cache-mode align\n  --speculative-config \'{"method":"mtp","num_speculative_tokens":1}\'\n')
    script.write_text(source)
    env.update(WARMUP_SCRIPT=str(ORIGINAL.with_name('vllm_prefix_warmup.py')),
               PROBE_SCRIPT=str(ORIGINAL.with_name('vllm_structured_output_probe.py')),
               VLLM_READY_FILE=str(ROOT/'mtp.ready'),VLLM_PROBE_REPORT_FILE=str(ROOT/'mtp-structured-probe.json'),
               VLLM_READY_TIMEOUT_SEC='900')
    cmd=['bash',str(script)]
else:
    log_file=ROOT/'restore-model.log'
    assert ORIGINAL.read_bytes()==(PRIVATE/'original.sh').read_bytes(), 'formal launcher changed during experiment'
    cmd=['bash',str(ORIGINAL)]
with log_file.open('wb') as output:
    process=subprocess.Popen(cmd,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
state={'mode':mode,'pid':process.pid,'command':cmd,
       'ready_file':env.get('VLLM_READY_FILE','/tmp/rs_agent_latency/vllm_qwen35_4b.ready'), 'log_file':str(log_file)}
FILE.write_text(json.dumps(state,indent=2))
print('模型实验已启动',mode,'PID',process.pid,flush=True)
