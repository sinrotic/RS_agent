"""等待固定模型扩库对照完成，再分析、导出并复核线上状态；只在离线目录写入。"""
import json,os,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v7_expansion')
PYTHON='/home/luo/RS_agent_remote/.venv/bin/python'


def save(value):
    p=ROOT/'final_status.json';t=p.with_suffix('.tmp');t.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)


def main():
    save({'state':'WAITING_FOR_COMPARISON','online_modified':False});deadline=time.time()+7200
    while True:
        status=json.loads((ROOT/'status.json').read_text())
        if status['state']=='FAILED':raise RuntimeError('comparison failed; do not package')
        if status['state']=='COMPLETE':break
        if time.time()>deadline:raise TimeoutError('comparison deadline')
        time.sleep(10)
    save({'state':'ANALYZING_AND_PACKAGING','online_modified':False})
    for script in ['analyze_product_v7_catalog.py','package_product_v7_catalog.py']:
        with (ROOT/(script+'.log')).open('w') as log:subprocess.run([PYTHON,str(ROOT/'scripts'/script),'--root',str(ROOT)],check=True,stdout=log,stderr=subprocess.STDOUT,timeout=1200)
    with urllib.request.urlopen('http://172.21.0.1:18120/health',timeout=5) as response:runtime=json.load(response)
    with urllib.request.urlopen('http://127.0.0.1:18213/actuator/health/readiness',timeout=5) as response:recommend=json.load(response)
    before=json.loads((ROOT/'online_before.json').read_text());assert runtime['model_sha256']==before[1]['model_sha256'] and runtime['status']=='UP' and recommend['status']=='UP'
    (ROOT/'online_final.json').write_text(json.dumps({'runtime':runtime,'recommend':recommend,'online_modified':False},indent=2))
    save({'state':'COMPLETE_OFFLINE_PACKAGES_VERIFIED','online_modified':False,'updated_unix':time.time()})


if __name__=='__main__':
    try:main()
    except Exception as e:save({'state':'FAILED','error':str(e),'online_modified':False});raise
