"""按私有快照恢复GPU1的Qwen服务；由训练单元ExecStopPost触发，异常退出也恢复。"""
import argparse,json,os,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v15_training')
SNAPSHOT=ROOT/'migration/qwen_service.private.json'
UNIT='rs-vllm-qwen35-restored-after-v15'

def healthy():
    try:
        with urllib.request.urlopen('http://127.0.0.1:18082/health',timeout=2) as response:return response.status==200
    except Exception:return False

def main(launch=False):
    state=json.loads(SNAPSHOT.read_text())
    assert state['env']['CUDA_VISIBLE_DEVICES']=='1' and state['restore_unit']==UNIT
    assert state['argv'][0]=='/mnt/data/luo/venvs/rsagent-vllm/bin/python'
    if launch:
        os.chdir(state['cwd']);os.execvpe(state['argv'][0],state['argv'],state['env'])
    if healthy():
        (ROOT/'qwen_restore_status.json').write_text(json.dumps({'state':'RESTORED_HEALTHY','port':18082,'gpu':1,'already_running':True,'timestamp':time.time()}));return
    active=subprocess.run(['systemctl','--user','is-active',UNIT],capture_output=True,text=True).stdout.strip()
    if active!='active':
        exists=subprocess.run(['systemctl','--user','show',UNIT,'--property=LoadState','--value'],capture_output=True,text=True).stdout.strip()
        if exists=='loaded':subprocess.run(['systemctl','--user','start',UNIT],check=True)
        else:
            subprocess.run(['systemd-run','--user','--unit='+UNIT,'--property=Restart=on-failure','--property=RestartSec=5',
                '/usr/bin/python3',str(ROOT/'scripts/restore_qwen_after_v15.py'),'--launch'],check=True)
    (ROOT/'qwen_restore_status.json').write_text(json.dumps({'state':'RESTORE_STARTED','unit':UNIT,'port':18082,'timestamp':time.time()}))
    for _ in range(60):
        if healthy():
            (ROOT/'qwen_restore_status.json').write_text(json.dumps({'state':'RESTORED_HEALTHY','unit':UNIT,'port':18082,'gpu':1,'timestamp':time.time()}))
            print('QWEN_RESTORED_HEALTHY',flush=True);return
        time.sleep(1)
    (ROOT/'qwen_restore_status.json').write_text(json.dumps({'state':'RESTORE_NOT_READY','unit':UNIT,'port':18082,'timestamp':time.time()}))
    raise RuntimeError('Qwen恢复启动后60秒内未就绪，请检查恢复单元；私有配置未输出')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--launch',action='store_true');main(p.parse_args().launch)
