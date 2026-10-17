"""隔离 Java 实例复用真实只读推荐依赖，公开报告只保存验收指标。"""
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import time
import urllib.request

import business_probe as probe

ROOT = Path(__file__).resolve().parent
probe.ROOT = ROOT
probe.BASE = 'http://127.0.0.1:18314'


def item_ids(final):
    ids=final.get('recommended_item_ids',final.get('recommendedItemIds'))
    if ids is None:
        ids=[item.get('item_id',item.get('itemId')) for item in
             final.get('recommended_items',final.get('recommendedItems',[]))]
    if not isinstance(ids,list) or any(not isinstance(value,str) or not value for value in ids):
        raise ValueError('公开商品列表畸形')
    return ids


def trace(session):
    request = urllib.request.Request(probe.BASE + '/api/platform/agent/' + session + '/turns',
                                     headers={'X-User-Roles':'OBSERVER'})
    with urllib.request.urlopen(request,timeout=15) as response:
        return json.load(response)


def summarize(row):
    final=row.get('response')
    if not final or row.get('error'):
        raise ValueError('没有完整最终回答')
    records=trace(row['session_id'])
    turns=records.get('turns',[])
    if not turns:
        raise ValueError('没有持久化工具审计记录')
    # 多轮只检查本轮；此前轮次已单独验收。
    turn=turns[-1]
    tools=turn.get('tool_calls',turn.get('toolCalls',[]))
    failed=sum(str(tool.get('status','')).upper()=='FAILED' for tool in tools)
    if failed:
        raise ValueError('实际工具执行失败')
    blocks=final.get('answer_blocks',final.get('answerBlocks',[]))
    if not blocks:
        blocks=[e['data'] for e in row.get('events',[]) if e['event']=='answer_block']
    text='\n'.join(block.get('content','') or '' for block in blocks)
    ids=item_ids(final)
    return {'query':row['query'],'elapsed_ms':row['agent_done_ms'],
            'complete_with_catalog_ms':row.get('complete_with_catalog_ms'),
            'finish_reason':final.get('finish_reason',final.get('finishReason')),
            'item_count':len(ids),'text_characters':len(text),'block_types':[b.get('type') for b in blocks],
            'tool_count':len(tools),'failed_tools':failed,
            'tool_names':[t.get('tool_name',t.get('toolName')) for t in tools],
            'answer_sha256':hashlib.sha256(json.dumps(blocks,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
            'passed':True},text


def advice(user, capture):
    query='选购通勤双肩包时，应该考虑哪些方面？请给出三条简短的一般建议，不推荐具体商品，不查询商品或用户历史。'
    token=user['accessToken']
    session=probe.http('/api/sessions',{'entryScene':'quantization-regression'},token)['sessionId']
    payload={'session_id':session,'profile_user_id':user['profileUserId'],'user_message':query,'limit':5,
             'context':{'scene':'agent_chat','client_turn_id':'quant-'+secrets.token_hex(12),'a2ui_state':[]}}
    headers={'Content-Type':'application/json','X-Account-Id':user['accountId'],
             'X-Profile-User-Id':user['profileUserId']}
    request=urllib.request.Request(probe.BASE+'/api/agent/chat/stream',headers=headers,
                                    data=json.dumps(payload,ensure_ascii=False).encode())
    start=time.perf_counter();events=[];event_name=''
    with urllib.request.urlopen(request,timeout=180) as response:
        for raw in response:
            line=raw.decode().strip()
            if line.startswith('event:'):event_name=line[6:].strip()
            if line.startswith('data:'):events.append({'event':event_name,'data':json.loads(line[5:].strip())})
    final=next((e['data'].get('response') for e in reversed(events) if e['event']=='done'),None)
    row={'query':query,'session_id':session,'events':events,'response':final,
         'agent_done_ms':round((time.perf_counter()-start)*1000,2)}
    capture(row)
    summary,text=summarize(row)
    numbered=len(re.findall(r'(?:^|\n|\s)[1-3一二三][.、．）)]',text))
    groups=[('肩带','背负','舒适'),('容量','分区','收纳','电脑'),('面料','防水','耐用','耐磨','防护'),('预算','价格')]
    topics=sum(any(word in text for word in group) for group in groups)
    complete=numbered>=3 or topics>=3
    summary['advice_complete']=complete
    summary['advice_respects_no_products']=summary['item_count']==0
    summary['passed']=complete and summary['advice_respects_no_products']
    return row,summary


def append_business(artifact):
    source=json.loads(artifact.read_text())
    expected=source.get('model_base','http://127.0.0.1:18092/v1')
    if expected=='18082':expected='http://127.0.0.1:18082/v1'
    container=json.loads(subprocess.check_output(['docker','inspect','rs-quantization-20261011-agent'],text=True))[0]
    environment=dict(x.split('=',1) for x in container['Config']['Env'] if '=' in x)
    if environment.get('RS_AGENT_OPENAI_BASE_URL')!=expected:
        raise ValueError('验收 Java 实例连接的模型与本次对照不一致')
    users=probe.accounts()
    rows=[];results=[]
    private=ROOT/(artifact.stem+'-business.private.json')
    def capture(row):
        rows.append(row)
        private.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
        private.chmod(0o600)
    queries=['推荐鼠标','推荐一款适合办公的鼠标，最好静音，说明理由','推荐适合编程使用的键盘，说明各自的区别']
    for number,query in enumerate(queries):
        row=probe.one(users[0],query,'fast','quant-single-'+str(number))
        capture(row)
        summary,text=summarize(row)
        if summary['item_count']!=5 or len(set(item_ids(row['response'])))!=5:
            raise ValueError('商品数量或去重失败')
        if number and not text.strip():
            raise ValueError('复杂推荐没有说明文字')
        results.append(summary)
    session=None
    for number,query in enumerate(['请帮我推荐鼠标','换一批鼠标，适合办公使用']):
        row=probe.one(users[1],query,'fast','quant-multi-'+str(number),session)
        capture(row)
        session=row['session_id']; summary,_=summarize(row)
        if summary['item_count']!=5: raise ValueError('多轮商品回答不完整')
        results.append(summary)
    for number in range(3):
        row,summary=advice(users[2],capture);results.append(summary)
    data=json.loads(artifact.read_text());data['business_regression']=results[:5]
    data['advice_diagnostic']=results[5:]
    artifact.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print('实际推荐与多轮 5/5 通过；一般建议通过数',sum(r['passed'] for r in results[5:]),'/3',flush=True)
