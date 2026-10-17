#!/usr/bin/env python3
"""本次多路召回发布：校验版本，备份，仅替换 Recommend，失败恢复。"""
import hashlib
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path


def main():
    root=Path('/home/luo/RS_agent_java')
    release=root/'releases/20260913-multi-recall'
    backup=root/'backups/20260913-multi-recall'
    jar=release/'rs-service-recommend-final.jar'
    expected='a8d38f15c3ec59314b0b9171065662f3f2cea358884f3fd084851ed688360199'
    assert hashlib.sha256(jar.read_bytes()).hexdigest()==expected
    assert hashlib.sha256((root/'services/rs-service-recommend.jar').read_bytes()).hexdigest()=='4d8bdc1bf64975c821cced2ec6a55fcf308c6c037c01f4f85b3c0626e6c56279', '线上版本已改变，请重新核验'
    with urllib.request.urlopen('http://172.21.0.1:18118/health',timeout=3) as response:
        runtime=json.load(response)
    assert runtime['status']=='UP' and runtime['version']=='multi_recall_20260913'
    assert json.loads((release/'multi-recall-acceptance.json').read_text())['status']=='PASS'
    assert json.loads((release/'index-verification.json').read_text())['status']=='PASS'
    backup.mkdir(parents=True,mode=0o700,exist_ok=False)
    files=['services/rs-service-recommend.jar','services/release-manifest.json','app_deploy/docker-compose.yml','app_deploy/docker-compose.override.yml','app_deploy/.env']
    for name in files:
        target=backup/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,target)
    command=['docker','compose','-p','rs-agent-java-app','-f','docker-compose.yml','-f','docker-compose.override.yml']
    def run(args): subprocess.run(command+args,cwd=root/'app_deploy',check=True,timeout=90,stdout=subprocess.DEVNULL)
    settings={'RS_RECOMMEND_MULTI_RECALL_ENABLED':'true','RS_RECOMMEND_MULTI_RECALL_BASE_URL':'http://172.21.0.1:18118','RS_RECOMMEND_MULTI_RECALL_VERSION':'multi_recall_20260913'}
    try:
        compose=root/'app_deploy/docker-compose.yml'
        value=compose.read_text()
        needle='      RS_RECOMMEND_TWO_TOWER_ENABLED: ${RS_RECOMMEND_TWO_TOWER_ENABLED:-false}\n'
        assert value.count(needle)==1 and 'RS_RECOMMEND_MULTI_RECALL_ENABLED' not in value
        additional=''.join('      '+k+': ${'+k+':-'+('false' if k.endswith('ENABLED') else v)+'}\n' for k,v in settings.items())
        compose.write_text(value.replace(needle,needle+additional))
        env=root/'app_deploy/.env'
        lines=[line for line in env.read_text().splitlines() if not any(line.startswith(k+'=') for k in settings)]
        env.write_text('\n'.join(lines+[k+'='+v for k,v in settings.items()])+'\n')
        run(['stop','-t','15','rs-service-recommend'])
        shutil.copy2(jar,root/'services/rs-service-recommend.jar')
        run(['up','-d','--no-deps','--force-recreate','rs-service-recommend'])
        for _ in range(50):
            try:
                with urllib.request.urlopen('http://127.0.0.1:18103/actuator/health/readiness',timeout=2) as response:
                    if json.load(response)['status']=='UP':break
            except Exception:pass
            time.sleep(1)
        else:raise RuntimeError('readiness failed')
        manifest={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root/'services').glob('*.jar'))}
        (root/'services/release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        report={'status':'PASS','recommend_sha256':expected,'runtime':runtime,'settings':settings,'backup':str(backup)}
        (release/'deployment-verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))
    except Exception:
        run(['stop','-t','15','rs-service-recommend'])
        for name in files:shutil.copy2(backup/name,root/name)
        run(['up','-d','--no-deps','--force-recreate','rs-service-recommend'])
        raise


if __name__=='__main__':main()
