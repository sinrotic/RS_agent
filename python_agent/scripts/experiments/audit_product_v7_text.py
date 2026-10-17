"""扩库文本完整性与重复文本审计；不改候选集合或编码。"""
import argparse,collections,hashlib,json,time
from pathlib import Path


def main(args):
    manifest=json.loads((args.data/'manifest.json').read_text());old_count=manifest['old_count'];started=time.time()
    groups={k:{'count':0,'empty_text':0,'empty_title':0,'characters':0,'categories':collections.Counter(),'exact_duplicate_text_rows':0} for k in ['old','new']}
    hashes=collections.Counter();old_hashes=set();new_matches_old=0;ids=set();ineligible=[]
    with (args.data/'items.jsonl').open(encoding='utf-8') as stream:
        for index,line in enumerate(stream):
            row=json.loads(line);assert row['index']==index and row['item_id'] not in ids;ids.add(row['item_id'])
            group='old' if index<old_count else 'new';stats=groups[group];text=row['text'].strip()
            stats['count']+=1;stats['empty_text']+=not bool(text);stats['empty_title']+=not bool(row['facts'][0]['text'].strip())
            if not text:ineligible.append({'index':index,'item_id':row['item_id'],'reason':'empty_text'})
            stats['characters']+=len(text);stats['categories'][row.get('category','')]+=1
            digest=hashlib.sha256(text.encode()).digest()
            if hashes[digest]:stats['exact_duplicate_text_rows']+=1
            if group=='new' and digest in old_hashes:new_matches_old+=1
            if group=='old':old_hashes.add(digest)
            hashes[digest]+=1
    assert len(ids)==manifest['total_count'] and groups['new']['count']==manifest['new_count']
    for stats in groups.values():stats['mean_characters']=stats['characters']/stats['count']
    result={'state':'COMPLETE','groups':groups,'ineligible':ineligible,'distinct_exact_texts':len(hashes),'max_exact_text_multiplicity':max(hashes.values()),
        'new_rows_sharing_exact_text_with_old':new_matches_old,'seconds':time.time()-started,
        'limitations':'重复文本不等价于商品重复或完整相关性；来源商品恢复指标会受到相似/同文商品竞争影响，未因此删商品或修改标签'}
    (args.data/'text_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);main(p.parse_args())
