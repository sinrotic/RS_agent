"""冻结验收结束后生成中文结果，保留失败配置和数据覆盖限制。"""
import json
from pathlib import Path
import numpy as np
from evaluate_product_v7_catalog import save
ROOT=Path('/mnt/data/luo/remote_runs/product_v10_training')
def read(name):return json.loads((ROOT/name).read_text())
def interval(before,after):
    def rr(x):
        x=np.asarray(x,dtype=float);return np.divide(1,x,out=np.zeros_like(x),where=x>0)
    delta=rr(after)-rr(before);rng=np.random.default_rng(20261011)
    values=[float(rng.choice(delta,len(delta),replace=True).mean()) for _ in range(2000)]
    return {'mrr_delta':float(delta.mean()),'paired_ci95':np.quantile(values,[.025,.975]).tolist(),'selection_adjusted':False}
def main():
    result=read('results.json');assert result['state']=='COMPLETE'
    selection=read('selection.json');final=read('final_validation.json');gate=read('serving_gate.json')
    deployment=read('deployment_status.json') if (ROOT/'deployment_status.json').exists() else {'state':'NOT_DEPLOYED'}
    text=['商品三塔 v10：MRR诊断与负样本/用户表示对照结果','',f'综合验收：{gate["state"]}；发布状态：{deployment["state"]}',
        f'冻结候选：{selection["selected"]}',f'检查点：{selection["checkpoint"]}',
        f'模型SHA256：{gate["model_sha256"]}','远程目录：'+str(ROOT),'',
        '结论按综合门槛执行，不以训练完成、单个开发点或只改善Top100代替头部验收。',
        'MRR下降主要来自扩库竞争及补全历史；同库同历史的候选权重改善了一部分MRR。',
        '历史样本集中损失在4-10项历史和原库已覆盖目标；少量同文本商品形成并列竞争，',
        '更明显的失败是跨品类新增历史拉偏用户向量。历史区间较宽，不宣称点估计具有显著性。','',
        '训练：GPU2，batch128，用户MLP lr5e-7，商品/BGE/查询塔冻结。',
        '八组筛选各4000步，同一2656780训练前缀样本的固定乱序。合格配置可继续同一epoch。',
        '开发集：已有1485、训练期新用户1500、新未来短历史1000；未使用封存选型。',
        '负例：127随机，或96随机+31共享4096池挖掘；困难项允许超过正商品得分；',
        '排除已知训练正例、空文本、同文本、正商品余弦>=0.97近重复。soft_hard权重0.1。',
        '表示：均值、0.8位置衰减、75%均值+25%最近3项、一致性降权（温度0.15）。',
        '一致性聚合在<=2项历史严格保持均值；没有以目标商品或验证标签计算注意力。','',
        '各训练配置末次开发MRR（实际选型可能选较早检查点或未续训候选）：',
        '配置 / 步数 / 已有开发 / 训练期新用户 / 未来短历史']
    for name,r in result['runs'].items():
        if r.get('checkpoints'):
            e=r['checkpoints'][-1];m=[e['evaluation'][k]['metrics']['mrr'] for k in ['existing_dev','fresh_dev','future_dev']]
            text.append(f'{name} / {e["step"]} / '+' / '.join(f'{x:.8f}' for x in m))
    text+=['','冻结后历史回归（1632用户；已见测试，不宣称独立）：','模型 / Hit10 / Hit100 / MRR']
    for name,key in [('online_actual','test/old_catalog'),('online_expanded','test/expanded_full_history'),('candidate','test/expanded_full_history')]:
        m=final['models'][name][key]['metrics'];text.append(f'{name} / {m["hit@10"]:.4%} / {m["hit@100"]:.4%} / {m["mrr"]:.8f}')
    text+=['','冻结后新未来封存（2000用户；未见标签，均两项已知历史）：','模型 / Hit10 / Hit100 / MRR']
    for name,e in result['sealed'].items():
        m=e['sealed_future']['metrics'];text.append(f'{name} / {m["hit@10"]:.4%} / {m["hit@100"]:.4%} / {m["mrr"]:.8f}')
    evidence={'historical':interval(final['models']['online_actual']['test/old_catalog']['ranks'],final['models']['candidate']['test/expanded_full_history']['ranks']),
        'sealed_future':interval(result['sealed']['online_actual']['sealed_future']['ranks'],result['sealed']['candidate']['sealed_future']['ranks'])}
    save(ROOT/'paired_mrr_evidence.json',evidence)
    text+=['','配对MRR差值与95%区间（未校正模型选择；历史样本已重复使用）：',json.dumps(evidence,ensure_ascii=False),
        '','工程验收：']+[f'{k}: {v}' for k,v in gate['checks'].items()]
    ann=read('ann_verification.json');text += [f'ANN Top100平均重叠：{ann["ann_overlap_at100_mean"]:.4%}，Milvus REST P95 {ann["milvus_rest_p95_ms"]:.2f}ms。',
        '5项训练/负例/聚合测试及实际CPU前向一致性测试通过；既有Java6项参数和服务测试通过。',
        '隔离候选服务18235、CPU运行时18126，模型维度1024，有效候选商品763080。','',
        '限制：未来封存只覆盖短历史；尚未使用的>=3历史测试用户已不存在，扫描尝试得到0。',
        '较长历史只有已见回归证据；不能据短历史改善宣称全用户泛化改善。',
        '候选及元数据沿用训练期快照；正序列来自评分评论，非实际购买完成事件。',
        '合成语义查询源商品恢复与标题关键词检查均为代理，不代表真实相关性或线上收益。']
    if deployment.get('rollback_command'):text+=['',f'回滚命令：{deployment["rollback_command"]}',f'旧容器保留：{deployment["backup_container"]}']
    (ROOT/'RESULTS.txt').write_text('\n'.join(text)+'\n',encoding='utf-8');print('REPORT_READY',gate['state'],deployment['state'])
if __name__=='__main__':main()
