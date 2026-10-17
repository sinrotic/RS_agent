"""汇总同一 GPU 后端的五组开发集对照，不发布模型或读取最终测试集。"""
import argparse
import json
from pathlib import Path

from finish_product_v5_comparison import paired


def analyze(root):
    names = ['replacement32_gpu_control', 'shuffle32', 'shuffle127', 'mixed127', 'attention_mixed127']
    results = {name: json.loads((root / name / 'results.json').read_text()) for name in names}
    for result in results.values():
        assert result['state'] == 'COMPLETE'
        assert result['config']['device'] == 'cuda'
        assert result['epochs'][-1]['epoch'] == 3
        assert result['epochs'][-1]['steps'] == 18186
        assert result['train_rows'] == 387951 and result['candidate_count'] == 203887
        assert result['config']['seed'] == 42
    evaluations = {name: value['epochs'][-1]['evaluation'] for name, value in results.items()}
    effects = {}
    for label, a, b in [
        ('full_traversal', names[0], names[1]),
        ('negative_count', names[1], names[2]),
        ('negative_mix', names[2], names[3]),
        ('user_attention', names[3], names[4]),
    ]:
        control, treatment = evaluations[a], evaluations[b]
        effects[label] = {
            'control': a, 'treatment': b,
            **paired(control['ranks'], treatment['ranks']),
            'mrr_delta': treatment['metrics']['mrr'] - control['metrics']['mrr'],
            'ndcg_delta': treatment['metrics']['ndcg@100'] - control['metrics']['ndcg@100'],
        }
    output = {
        'scope': '开发集1000用户、固定seed42、统一第3轮；区间未校正多重比较，不能代替独立测试或线上收益',
        'online_modified': False,
        'runs': {name: {
            'metrics': evaluations[name]['metrics'],
            'history_groups': evaluations[name]['groups'],
            'epoch_hit100': [e['evaluation']['metrics']['hit@100'] for e in value['epochs']],
            'epoch_unique_fraction': [e['epoch_unique_fraction'] for e in value['epochs']],
            'training_seconds': value['seconds'],
            'peak_cuda_gib': value.get('peak_cuda_gib'),
            'best_epoch': value.get('best_epoch'),
        } for name, value in results.items()},
        'effects': effects,
        'coverage_limit': '候选集仅覆盖61.7%的开发集目标；完整遍历指现有387951条训练样本，不代表全部原始用户或全商品目录',
    }
    (root / 'gpu_analysis.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'runs': {n: r['metrics'] for n, r in output['runs'].items()}, 'effects': effects}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    analyze(parser.parse_args().root)
