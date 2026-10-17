"""兼容教师故障：只启动隔离故障容器，绝不停止仍服务现网的旧运行时。"""
import json,os,subprocess,sys,time,urllib.request
from pathlib import Path
from serve_product_v14 import wait_health
sys.path.insert(0,'/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
from probe import accounts,http
ROOT=Path('/mnt/data/luo/remote_runs/product_v14_training')
NAME='rs-product-v14-guard-fault'

def main():
    names=subprocess.check_output(['docker','ps','-a','--format','{{.Names}}'],text=True).splitlines();assert NAME not in names
    snapshot=json.loads(subprocess.check_output(['docker','inspect','rs-product-v14-candidate']))[0]
    env=dict(x.split('=',1) for x in snapshot['Config']['Env'])
    env.update(SERVER_PORT='18239',RS_RECOMMEND_TWO_TOWER_PROTECTED_BASE_URL='http://172.21.0.1:18134')
    private=ROOT/'deployment/guard-fault.private.env';private.write_text('\n'.join(k+'='+v for k,v in env.items()));private.chmod(0o600)
    cmd=['docker','run','-d','--name',NAME,'--network','host','--env-file',str(private)]
    for bind in snapshot['HostConfig']['Binds']:cmd.extend(['-v',bind])
    cmd.extend([snapshot['Image']]+snapshot['Config']['Cmd'])
    started=False
    try:
        subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL);started=True;wait_health(18239)
        a=accounts()[6];session=http('/api/sessions',{'entryScene':'v14-protected-fault'},a['accessToken'])['sessionId']
        request=urllib.request.Request('http://127.0.0.1:18239/api/recommend/home',
            data=json.dumps({'session_id':session,'scene':'home','page_size':6,'debug':True}).encode(),
            headers={'Content-Type':'application/json','X-Account-Id':a['accountId'],'X-Profile-User-Id':a['profileUserId']})
        with urllib.request.urlopen(request,timeout=60) as f:home=json.load(f)
        passed=len(home['items'])==6 and 'two_tower_unavailable' in home['degradation_reasons']
        wait_health(18120,'172.21.0.1','/health');wait_health(18132,'172.21.0.1','/health');wait_health(18213)
        report={'state':'PASS' if passed else 'FAIL','home_count':len(home['items']),'degradation_reasons':home['degradation_reasons'],
                'old_runtime_stopped':False,'main_runtime_healthy':True,'fault_port':18239,'timestamp':time.time()}
        (ROOT/'guard_fault_replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('PROTECTED_TEACHER_FAULT',report['state'])
        assert passed
    finally:
        if started:
            assert NAME=='rs-product-v14-guard-fault'
            subprocess.run(['docker','stop',NAME],check=True,stdout=subprocess.DEVNULL)
            subprocess.run(['docker','rm',NAME],check=True,stdout=subprocess.DEVNULL)

if __name__=='__main__':
    os.umask(0o077);main()
