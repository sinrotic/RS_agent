import importlib.util
import json
from pathlib import Path

spec=importlib.util.spec_from_file_location('comparison_runner',Path(__file__).parents[1]/'scripts/experiments/run_product_v4_comparison.py')
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_completed_run_is_not_launched_twice(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'ROOT',tmp_path)
    folder=tmp_path/'rec_seed42';folder.mkdir()
    (folder/'results.json').write_text(json.dumps({'seconds':1.2}))
    def unexpected(*args,**kwargs):
        raise AssertionError('must not relaunch completed run')
    monkeypatch.setattr(runner.subprocess,'run',unexpected)
    runner.launch('rec_seed42','rec',42)


def test_paired_seed_average_uses_per_user_hits(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'ROOT',tmp_path)
    # 两个用户中，第一个从未命中变为命中，第二个保持命中：差值为0.5。
    for mode in ['rec','semantic','joint']:
        for seed in runner.SEEDS:
            folder=tmp_path/f'{mode}_seed{seed}';folder.mkdir()
            ranks=[200,1] if mode=='rec' else [1,1]
            (folder/'results.json').write_text(json.dumps({'checkpoints':[{'evaluation':{'rec_ranks':ranks}}]}))
    runner.summarize()
    result=json.loads((tmp_path/'comparison_results.json').read_text())
    assert result['joint_minus_rec_hit100']['delta']==.5
    assert result['joint_minus_rec_hit100']['paired_user_95pct']==[0.,1.]
