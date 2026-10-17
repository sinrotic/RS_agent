"""固定模型输入的建议完整性、算术与澄清回归，避免应用意图路由干扰。"""
import argparse
import json
from pathlib import Path
import time
import urllib.request
from jsonschema import Draft202012Validator


def run(base):
    advice={'type':'object','properties':{'suggestions':{'type':'array','minItems':3,'maxItems':3,
            'items':{'type':'string','minLength':12}}},'required':['suggestions'],'additionalProperties':False}
    math={'type':'object','properties':{'total':{'type':'integer'},'remaining':{'type':'integer'}},
          'required':['total','remaining'],'additionalProperties':False}
    clarify={'type':'object','properties':{'question':{'type':'string','minLength':5}},
             'required':['question'],'additionalProperties':False}
    cases=[('advice_'+str(i),'选购通勤双肩包时应该考虑哪些方面？给出三条简短一般建议，不推荐商品，不查询历史。',advice) for i in range(3)]
    cases += [('budget_math','预算300元，商品单价129元，买2件，运费20元。计算总支出和剩余预算。',math),
              ('clarify_budget','我想买日常通勤背包，还没确定预算。只问我预算，不检索商品。',clarify),
              ('clarify_size','我要背电脑通勤，但不知道背包应该多大。只问我的电脑尺寸，不检索商品。',clarify)]
    results=[]
    for label,prompt,schema in cases:
        payload={'model':'qwen35-4b','messages':[{'role':'system','content':'如实回答用户，按指定工具返回完整结果。'},
                    {'role':'user','content':prompt}],'temperature':0,'max_tokens':1024,'stream':False,
                 'chat_template_kwargs':{'enable_thinking':False},'parallel_tool_calls':False,
                 'tools':[{'type':'function','function':{'name':'report_result','description':'报告结果','strict':True,'parameters':schema}}],
                 'tool_choice':{'type':'function','function':{'name':'report_result'}}}
        request=urllib.request.Request(base+'/chat/completions',data=json.dumps(payload,ensure_ascii=False).encode(),
                                       headers={'Content-Type':'application/json'})
        start=time.perf_counter()
        with urllib.request.urlopen(request,timeout=90) as response: body=json.load(response)
        choice=body['choices'][0]
        assert choice['finish_reason'] in ['stop','tool_calls'], '输出未完成'
        calls=choice['message'].get('tool_calls',[])
        assert len(calls)==1 and calls[0]['function']['name']=='report_result'
        arguments=json.loads(calls[0]['function']['arguments']);Draft202012Validator(schema).validate(arguments)
        if label.startswith('advice'):
            text='\n'.join(arguments['suggestions'])
            groups=[('肩带','背负','舒适'),('容量','分区','收纳','电脑'),('面料','防水','耐用','耐磨','防护'),('预算','价格')]
            assert sum(any(word in text for word in group) for group in groups)>=3, '三条建议缺少主题覆盖'
        elif label=='budget_math': assert arguments=={'total':278,'remaining':22}
        elif label=='clarify_budget': assert '预算' in arguments['question']
        elif label=='clarify_size': assert any(word in arguments['question'] for word in ('尺寸','英寸','多大'))
        results.append({'case':label,'passed':True,'elapsed_ms':round((time.perf_counter()-start)*1000,2),
                        'usage':body['usage'],'result':arguments})
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.write_text(json.dumps({'passed':True,'results':run(args.base_url)},ensure_ascii=False,indent=2)+'\n')
    print('固定输入建议、算术与澄清 6/6 通过',flush=True)
