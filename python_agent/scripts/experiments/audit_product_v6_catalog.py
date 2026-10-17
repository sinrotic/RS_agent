"""仅统计训练期正反馈商品规模；不按确认集目标扩词表，不修改候选选择。"""
import argparse,json,time
from pathlib import Path


def read(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:yield json.loads(line)


def main(args):
    manifest=json.loads((args.data/'data_manifest.json').read_text());source=Path(manifest['source'])
    current={r['item_id'] for r in read(args.data/'items.jsonl')};positive=set();rows=0;start=time.time()
    for r in read(source/'user_sequences.train.jsonl'):
        assert len(r['recent_positive_item_sequence'])==len(r['recent_positive_timestamp_sequence'])
        assert all(t<manifest['train_cutoff'] for t in r['recent_positive_timestamp_sequence'])
        positive.update(r['recent_positive_item_sequence']);rows+=1
    result={'train_sequence_rows':rows,'current_candidate_items':len(current),'all_retained_train_positive_items':len(positive),
        'additional_train_positive_items':len(positive-current),'current_items_outside_retained_positive_histories':len(current-positive),
        'dense_1024_float32_gib':len(positive)*1024*4/2**30,'seconds':time.time()-start,
        'limitations':['来源历史最多保留50项，不能宣称完整训练期所有商品','本审计不读取开发/确认目标，不作为按目标补齐词表的依据','当前候选与模型不变；后续扩容须统一重评基线与候选']}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
