"""核验每个 Turn 实际调用模型，并以完整耗时检验目标。"""
import argparse
import json
from pathlib import Path
import statistics
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE=Path(__file__).resolve().parent
parser=argparse.ArgumentParser();parser.add_argument('phase');parser.add_argument('--target-ms',type=float,default=300)
args=parser.parse_args();data=json.loads((HERE/(args.phase+'.json')).read_text(encoding='utf-8'))
wire=[json.loads(line) for line in (HERE/'model-wire.jsonl').read_text(encoding='utf-8').splitlines()]
values=[row for rows in data.values() for row in rows]
summary=[]
for row in values:
    start=row.get('start_epoch_ms',0); end=start+row.get('agent_done_ms',0)
    calls=[call for call in wire if call['phase']==args.phase and start<=call['epoch_ms']<=end]
    card = (row.get('response') or {}).get('card_set_id')
    if 'concurrent' in args.phase and card:
        calls = [call for call in calls if call.get('recommendation_card_set_id') == card]
    summary.append({'label':row['label'],'query':row['query'],'complete_ms':row.get('complete_with_catalog_ms'),
                    'failed':not bool(row.get('response')),'llm_calls':len(calls),
                    'llm_total_ms':sum(call['elapsed_ms'] for call in calls),
                    'completion_tokens':sum(call.get('usage',{}).get('completion_tokens',0) for call in calls),
                    'tool_names':[name for call in calls for name in call['tool_names']],
                    'finish_reasons':[reason for call in calls for reason in call['finish_reasons']],
                    'first_delta_ms':[call.get('first_delta_ms') for call in calls]})
successful=[row['complete_ms'] for row in summary if row['complete_ms']]
result={'phase':args.phase,'target_ms':args.target_ms,'requests':summary,
        'complete_median_ms':statistics.median(successful) if successful else None,
        'failed':len(data['failures']),
        'target_met':all(row['complete_ms'] and row['llm_calls'] and row['complete_ms']<=args.target_ms for row in summary)}
(HERE/(args.phase+'-summary.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(0 if result['target_met'] else 1)
