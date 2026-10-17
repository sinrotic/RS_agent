"""单独验证慢模型不会被原 30 秒 SSE 默认期限截断；不计入性能数据。"""
import json
from probe import ROOT,accounts,one
from measure import ready

ready(); users=accounts(); (ROOT/'phase.txt').write_text('timeout-probe')
row=one(users[0],'推荐鼠标','fast','timeout-probe')
(ROOT/'timeout-probe.json').write_text(json.dumps(row,ensure_ascii=False,indent=2))
assert row.get('response') and not row.get('error')
assert row['agent_done_ms']>35000
assert row['history']['turns'][-1]['finish_reason']=='FINAL_ANSWER'
assert len(row['response']['recommended_items'])==5
wire=[json.loads(line) for line in (ROOT/'model-wire.jsonl').read_text().splitlines()]
calls=[call for call in wire if call['phase']=='timeout-probe'
       and row['start_epoch_ms']<=call['epoch_ms']<=row['start_epoch_ms']+row['agent_done_ms']]
assert len(calls)==1 and calls[0]['injected_delay_ms']==35000
assert calls[0]['tool_names']==['emit_final_answer']
(ROOT/'phase.txt').write_text('verified')
print('慢模型 SSE 正确性验收通过；人工延迟样本不计入性能统计',flush=True)
