"""最小结构化 LLM 调用的延迟下界探测，不代替完整推荐验收。"""
import json
from pathlib import Path
import statistics
import sys
import time
import urllib.request

ROOT=Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
schema={'type':'object','properties':{'category':{'type':'string','enum':['mouse','keyboard','headphones']},'quiet':{'type':'boolean'}},'required':['category','quiet'],'additionalProperties':False}
request={'model':'qwen35-4b','messages':[{'role':'system','content':'将购物需求解析为品类和是否要求静音，准确调用工具。'},{'role':'user','content':'推荐一款适合办公的鼠标，最好静音。'}],
         'tools':[{'type':'function','function':{'name':'recommend','description':'解析购物需求','strict':True,'parameters':schema}}],
         'tool_choice':{'type':'function','function':{'name':'recommend'}},'parallel_tool_calls':False,
         'chat_template_kwargs':{'enable_thinking':False},'max_tokens':64,'temperature':0,'stream':False}
result=[]
for i in range(6):
    begin=time.perf_counter()
    with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:18082/v1/chat/completions',data=json.dumps(request,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'}),timeout=90) as response:
        value=json.load(response)
    elapsed=(time.perf_counter()-begin)*1000
    args=json.loads(value['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    assert args=={'category':'mouse','quiet':True},args
    result.append({'ms':elapsed,'usage':value['usage']})
summary={'scope':'最小 LLM 结构化解析，不含推荐服务、保存或详情','calls':result,'warm_median_ms':statistics.median(row['ms'] for row in result[1:]),'under_300ms':all(row['ms']<=300 for row in result[1:])}
name=sys.argv[1] if len(sys.argv)>1 else 'model-floor'
(ROOT/(name+'.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps(summary,ensure_ascii=False),flush=True)
sys.exit(0 if summary['under_300ms'] else 1)
