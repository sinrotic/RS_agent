#!/usr/bin/env python3
"""真实六路索引、Java 首页、故障与换批验收；隔离交付，不修改用户偏好。"""
import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from personalized_home_acceptance import http
from feedback_acceptance import sql


SOURCES = ['itemcf_weak','itemcf_strong','swing_recall','usercf_recall','category','popular']
ROOT = Path('/home/luo/RS_agent_java')


def run(command):
    return subprocess.run(command,capture_output=True,text=True,check=True,timeout=90).stdout


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--jar',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    report={'checks':[],'profiles':[]}
    config=json.loads(run(['docker','inspect','rs-agent-java-service-recommend']))[0]
    original=dict(value.split('=',1) for value in config['Config']['Env'])
    service='rs-multi-acceptance-'+secrets.token_hex(4)
    db=sqlite3.connect(f'file:{ROOT}/data/models/multi_recall_20260913/candidates.sqlite?mode=ro&immutable=1',uri=True)
    profiles=[r[0] for r in db.execute("SELECT user FROM user_lists WHERE source='usercf_recall' LIMIT 12")]
    db.close()
    profiles+=sql('SELECT user_id FROM (SELECT user_id FROM amazon_reviews_base WHERE rating>=4 LIMIT 10000) r GROUP BY user_id HAVING COUNT(*)>=2 LIMIT 4').splitlines()
    def start(url):
        env={**original,'SPRING_APPLICATION_NAME':service,'SPRING_CLOUD_NACOS_DISCOVERY_ENABLED':'false',
             'SPRING_CLOUD_DISCOVERY_ENABLED':'false','RS_RECOMMEND_FEEDBACK_PERSISTENCE':'memory',
             'RS_RECOMMEND_FEEDBACK_PROJECTION':'memory','RS_RECOMMEND_MULTI_RECALL_ENABLED':'true',
             'RS_RECOMMEND_MULTI_RECALL_BASE_URL':url,'RS_RECOMMEND_MULTI_RECALL_VERSION':'multi_recall_20260913',
             'JAVA_OPTS':'-Xms128m -Xmx512m'}
        with tempfile.NamedTemporaryFile(mode='w',delete=False) as handle:
            path=Path(handle.name);os.chmod(path,0o600)
            handle.write('\n'.join(k+'='+v for k,v in env.items())+'\n')
        try:
            run(['docker','run','-d','--name',service,'--network','rs-agent-java_default','--env-file',str(path),
                 '-p','127.0.0.1:18133:18103','-v',str(Path(args.jar).resolve())+':/app/rs-service-recommend.jar:ro',
                 config['Config']['Image'],'sh','-c','java $JAVA_OPTS -jar /app/rs-service-recommend.jar'])
        finally: path.unlink()
        for _ in range(50):
            try:
                if http('http://127.0.0.1:18133','/actuator/health/readiness',timeout=2)['status']=='UP':return
            except Exception: pass
            time.sleep(1)
        raise AssertionError('service readiness timeout')
    def page(profile,cursor=''):
        result=http('http://127.0.0.1:18133','/api/recommend/home',{'session_id':service,'scene':'home','page_size':6,'cursor':cursor},
                    headers={'X-Account-Id':service,'X-Profile-User-Id':profile})
        trace=http('http://127.0.0.1:18133','/api/platform/recommend/'+result['request_id']+'/trace')
        assert len(result['items'])==6
        return result,trace
    try:
        start('http://172.21.0.1:18118')
        contributions=dict.fromkeys(SOURCES,0)
        displayed=dict.fromkeys(SOURCES,0)
        for profile in dict.fromkeys(profiles):
            begin=time.monotonic()
            diagnostic=http('http://127.0.0.1:18133','/internal/recommend/pipeline/recall',
                            {'profile_user_id':profile,'sources':SOURCES,'limit':500})
            assert diagnostic['candidate_count']==len(diagnostic['candidates'])
            for source,count in diagnostic['source_distribution'].items():
                assert count==sum(c['source']==source for c in diagnostic['candidates'])
            first,trace=page(profile)
            assert not first['degradation_reasons'],first['degradation_reasons']
            second,_=page(profile,first['next_cursor'])
            assert not second['degradation_reasons']
            assert {c['item_id'] for c in first['items']}.isdisjoint(c['item_id'] for c in second['items'])
            for source in SOURCES:
                contributions[source]+=trace['source_distribution'].get(source,0)
                displayed[source]+=sum(source in c['source_tags'] for c in first['items'])
            report['profiles'].append({'profile_hash':hashlib.sha256(profile.encode()).hexdigest(),
                 'source_distribution':trace['source_distribution'],'diagnostic':diagnostic['source_distribution'],
                 'first_page':first['items'],'two_pages_and_diagnostic_ms':round((time.monotonic()-begin)*1000,1)})
            print('PASS',trace['source_distribution'],flush=True)
        cold,trace=page('unknown-'+service)
        assert trace['source_distribution'].get('popular',0)>0
        assert all(trace['source_distribution'].get(s,0)==0 for s in SOURCES[:4])
        report['cold_sources']=trace['source_distribution']
        assert all(contributions[s]>0 for s in SOURCES if s!='popular'),contributions
        assert sum(displayed[s] for s in SOURCES[:4])>0,displayed
        report['contributions']=contributions; report['displayed']=displayed
        report['checks'].append('六路真实检索、实际统计、多画像首页、协同来源展示、换批去重、冷启动热门兜底')
        run(['docker','rm','-f',service]);start('http://127.0.0.1:9')
        failed,_=page(profiles[0])
        assert 'multi_recall_unavailable' in failed['degradation_reasons']
        report['checks'].append('新增召回故障不阻断原首页，响应明确降级')
        report['status']='PASS'
    finally:
        logs=subprocess.run(['docker','logs','--tail','80',service],capture_output=True,text=True,timeout=15)
        Path(args.output+'.service.log').write_text(logs.stdout+logs.stderr)
        subprocess.run(['docker','rm','-f',service],capture_output=True,timeout=45)
        Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
