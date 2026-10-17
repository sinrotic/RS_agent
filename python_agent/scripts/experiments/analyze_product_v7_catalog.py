"""分解扩库覆盖收益、旧目标竞争损失、补全历史收益；汇总固定模型对照。"""
import argparse,json
from pathlib import Path
import numpy as np


def hit(ranks):
    x=np.asarray(ranks);return (x>0)&(x<=100)


def main(args):
    result=json.loads((args.root/'comparison.json').read_text());assert result['state']=='COMPLETE'
    analysis={'eligible_candidate_count':result['eligible_candidate_count'],'excluded_empty_text':len(result['excluded_empty_text']),
              'metrics':{},'decomposition':{},'paired_comparisons':result['comparisons'],
              'scope':'同一批已经复评过的valid用户；两版模型权重固定；不推断线上转化收益'}
    for name,model in result['models'].items():
        ev=model['evaluations'];analysis['metrics'][name]={}
        for size in ['old','expanded']:
            for key,value in ev[size].items():analysis['metrics'][name][size+'/'+key]=value['metrics']
        analysis['decomposition'][name]={}
        for cohort in ['rec_dev','rec_confirm']:
            old=ev['old'][cohort+'/old_catalog'];fixed=ev['expanded'][cohort+'/expanded_fixed_history'];full=ev['expanded'][cohort+'/expanded_full_history']
            a,b,c=hit(old['ranks']),hit(fixed['ranks']),hit(full['ranks'])
            with (args.root/'data'/(cohort+'.jsonl')).open() as stream:records=[json.loads(line) for line in stream]
            newly=np.array([r['old_target']<0 and r['target']>=0 for r in records])
            added=int((b&newly).sum());lost=int((a&~b).sum())
            assert int(b.sum()-a.sum())==added-lost
            analysis['decomposition'][name][cohort]={'users':len(a),'old_hits':int(a.sum()),'expanded_fixed_history_hits':int(b.sum()),'expanded_full_history_hits':int(c.sum()),
                'new_target_hits_from_expansion':added,'old_target_hits_lost_to_more_candidates':lost,
                'history_completion_gained_hits':int((c&~b).sum()),'history_completion_lost_hits':int((b&~c).sum()),
                'target_group_metrics':full['target_groups']}
    (args.root/'analysis.json').write_text(json.dumps(analysis,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(analysis,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);main(p.parse_args())
