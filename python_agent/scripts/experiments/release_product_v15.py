"""等完整训练和Qwen恢复后串行验收；全部通过才切换，任一失败保留现网。"""
import json,os,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v15_training');PYTHON='/home/luo/RS_agent_remote/.venv/bin/python'

def write(state,**details):
    payload={'state':state,'timestamp':time.time(),**details}
    path=ROOT/'release_progress.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2));tmp.replace(path)
    print(json.dumps(payload,ensure_ascii=False),flush=True)

def read(name):return json.loads((ROOT/name).read_text())

def run(script,*args):
    write('VERIFYING',stage=script)
    env={**os.environ,'CUDA_VISIBLE_DEVICES':'1','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
    subprocess.run([PYTHON,str(ROOT/'scripts'/script),*args],env=env,check=True)

def main():
    write('WAITING_FULL_TRAINING');deadline=time.time()+7200
    while True:
        if (ROOT/'failure.json').exists():raise RuntimeError('训练失败：'+read('failure.json')['error'])
        if (ROOT/'results.json').exists() and read('results.json')['state']=='COMPLETE':break
        assert time.time()<deadline,'等待完整训练超时';time.sleep(5)
    # results COMPLETE写出后进程还会退出，再由ExecStopPost释放训练GPU并恢复Qwen。
    write('WAITING_QWEN_RESTORE');deadline=time.time()+600
    while True:
        try:
            restored=read('qwen_restore_status.json')['state']=='RESTORED_HEALTHY'
            with urllib.request.urlopen('http://127.0.0.1:18082/health',timeout=3) as response:healthy=response.status==200
            if healthy:
                if not restored:run('restore_qwen_after_v15.py')
                if read('qwen_restore_status.json')['state']=='RESTORED_HEALTHY':break
        except Exception:pass
        assert time.time()<deadline,'Qwen恢复未通过，保留现网';time.sleep(5)
    run('validate_product_v15.py')
    if read('final_validation.json')['state']!='PASS':
        write('QUALITY_FAILED_CURRENT_SERVICE_RETAINED',checks=read('final_validation.json')['checks'])
        run_report();return
    run('serve_product_v15.py','package');run('index_product_v15.py');run('serve_product_v15.py','candidate')
    run('check_product_v15_ann.py','--ef','4096');run('check_product_v15_java_route.py');run('audit_product_v15.py')
    run('replay_product_v15.py','--port','18213','--output','baseline_replay.json')
    run('replay_product_v15.py','--port','18240','--output','candidate_replay.json');run('gate_product_v15.py')
    if read('serving_gate.json')['state']!='PASS':
        write('SERVING_FAILED_CURRENT_SERVICE_RETAINED',checks=read('serving_gate.json')['checks'])
        run_report();return
    run('serve_product_v15.py','promote')
    assert read('deployment_status.json')['state']=='DEPLOYED_VERIFIED'
    write('DEPLOYED_VERIFIED',model=read('deployment_status.json')['model_key'],protected_head_count=0)
    run_report()

def run_report():
    # 保留最终发布状态，不把生成报告改写为VERIFYING。
    subprocess.run([PYTHON,str(ROOT/'scripts/finalize_product_v15.py')],check=True)

if __name__=='__main__':
    try:main()
    except Exception as e:
        write('FAILED_CURRENT_SERVICE_RETAINED_OR_ROLLED_BACK',error=repr(e));raise
