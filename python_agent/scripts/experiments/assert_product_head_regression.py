"""秒级头部回归反馈环；从冻结模型精确rank重算MRR，不能只信汇总PASS。"""
import argparse,json
from pathlib import Path
def main(p):
    d=json.loads(p.read_text());models=d['models']
    a=models['online_actual']['test/old_catalog'];b=models['candidate']['test/expanded_full_history']
    assert len(a['ranks'])==len(b['ranks'])
    def mrr(x):return sum(1/r if r>0 else 0 for r in x)/len(x)
    def head(x):return sum(0<r<=10 for r in x)
    before,after=mrr(a['ranks']),mrr(b['ranks'])
    assert abs(before-a['metrics']['mrr'])<1e-10 and abs(after-b['metrics']['mrr'])<1e-10
    out={'online_mrr':before,'candidate_mrr':after,'ratio':after/before,'online_hit10_count':head(a['ranks']),
        'candidate_hit10_count':head(b['ranks']),'mrr_pass':after>=.95*before,'head_pass':head(b['ranks'])>=head(a['ranks'])}
    print(json.dumps(out));return 0 if out['mrr_pass'] and out['head_pass'] else 1
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('validation',type=Path);raise SystemExit(main(p.parse_args().validation))
