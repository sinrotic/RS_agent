"""冻结稳定单模型，重新验收隔离部署；全部通过后切换核心服务。"""
import json,os,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v16_final');PYTHON='/home/luo/RS_agent_remote/.venv/bin/python'

def write(state,**details):
    record={'state':state,'timestamp':time.time(),**details};tmp=ROOT/'release_progress.tmp'
    tmp.write_text(json.dumps(record,ensure_ascii=False,indent=2));tmp.replace(ROOT/'release_progress.json');print(json.dumps(record,ensure_ascii=False),flush=True)

def read(name):return json.loads((ROOT/name).read_text())

def run(script,*args):
    write('VERIFYING',stage=script)
    subprocess.run([PYTHON,str(ROOT/'scripts'/script),*args],env={**os.environ,'CUDA_VISIBLE_DEVICES':'1','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'},check=True)

def main():
    with urllib.request.urlopen('http://127.0.0.1:18082/health',timeout=5) as f:assert f.status==200
    run('serve_product_final.py','package');run('index_product_final.py');run('serve_product_final.py','candidate')
    run('check_product_final_ann.py','--ef','4096');run('check_product_final_java_route.py');run('audit_product_final.py')
    run('replay_product_final.py','--port','18213','--output','baseline_replay.json')
    run('replay_product_final.py','--port','18242','--output','candidate_replay.json');run('gate_product_final.py')
    assert read('serving_gate.json')['state']=='PASS','最终版本服务验收未通过，保留现网'
    run('serve_product_final.py','promote');assert read('deployment_status.json')['state']=='DEPLOYED_VERIFIED'
    write('DEPLOYED_VERIFIED',model='product_three_tower_final_v1',protected_head_count=0)
    subprocess.run([PYTHON,str(ROOT/'scripts/finalize_product_final.py')],check=True)

if __name__=='__main__':
    try:main()
    except Exception as e:write('FAILED_CURRENT_RETAINED_OR_ROLLED_BACK',error=repr(e));raise
