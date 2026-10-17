"""所有请求必须经过 Qwen，完整回答加真实商品详情；保留失败。"""
import json
import sys
from probe import ROOT,accounts,one
from measure import ready

ready(); users=accounts(); name=sys.argv[1] if len(sys.argv)>1 else 'baseline'
(ROOT/'phase.txt').write_text(name)
result={'single':[],'multi_turn':[],'failures':[]}
def collect(group,user,query,label,session=None):
    try: row=one(user,query,'fast',label,session)
    except Exception as error: row={'query':query,'label':label,'error':str(error)}
    result[group if row.get('response') else 'failures'].append(row)
    (ROOT/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return row
for i,query in enumerate(('推荐鼠标','推荐鼠标','推荐一款适合办公的鼠标，最好静音，说明理由','推荐适合编程使用的键盘，说明各自的区别')):
    collect('single',users[0],query,'llm-'+str(i))
session=None
for i,query in enumerate(('请帮我推荐鼠标','换一批鼠标，适合办公使用','再推荐五款鼠标，说明理由')):
    row=collect('multi_turn',users[1],query,'multi-'+str(i),session); session=row.get('session_id',session)
print('经过 LLM 的完整流程测试结束，失败数',len(result['failures']),flush=True)
