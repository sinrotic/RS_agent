"""如实记录训练负结果、组合路线收益、冻结验收与已经完成的核心部署。"""
import json,time
from pathlib import Path
import numpy as np
ROOT=Path('/mnt/data/luo/remote_runs/product_v14_training');BASE=ROOT.parent

def read(name):return json.loads((ROOT/name).read_text())
def interval(before,after):
    def rr(x):
        a=np.asarray(x,dtype='float64');return np.divide(1,a,out=np.zeros_like(a),where=a>0)
    delta=rr(after)-rr(before);rng=np.random.default_rng(20261012)
    boot=[float(rng.choice(delta,len(delta),replace=True).mean()) for _ in range(2000)]
    return {'mrr_delta':float(delta.mean()),'paired_ci95':np.quantile(boot,[.025,.975]).tolist(),'selection_adjusted':False}

def main():
    final=read('final_validation.json');result=read('results.json');gate=read('serving_gate.json');deployment=read('deployment_status.json')
    assert gate['state']==final['state']==result['sealed_state']=='PASS' and deployment['state']=='DEPLOYED_VERIFIED'
    assert read('gateway_replay.json')['state']==read('actual_java_live_route_replay.json')['state']=='PASS'
    v12=json.loads((BASE/'product_v12_training/results.json').read_text());v13=json.loads((BASE/'product_v13_training/results.json').read_text())
    evidence={'historical':interval(final['models']['online_actual']['test/old_catalog']['ranks'],final['models']['candidate']['test/expanded_full_history']['ranks']),
              'new_rolling_sealed':interval(result['sealed']['online_actual']['sealed_future']['ranks'],result['sealed']['candidate']['sealed_future']['ranks'])}
    (ROOT/'paired_mrr_evidence.json').write_text(json.dumps(evidence,indent=2))
    text=['商品三塔后续探索与核心召回发布：v12/v13/v14（2026-10-12）','',
          '结论：找到并接入通过冻结效果与工程验收的组合路线。v14不是一个新单模型全面胜出的宣称。',
          '主体使用已训练商品三塔的最佳历史一致性聚合、扩展到763080件有效候选；',
          '同一召回预算先保留现网v4最多10个未看过的头部商品，再按新三塔顺序补齐并去重。',
          '查询仍使用新三塔查询投影，不应用旧头部保护。两空间余弦分数不相互比较。',
          '首页主召回占兴趣预算65%，回放为270-271项，其中保护项最多10个，其余由新三塔提供。',
          '其他协同/语义/类目/探索召回及后续排序沿用原服务包。最终展示仍经过既有排序、偏好和去重。','',
          '训练探索：GPU2 RTX4090，batch128，训练显存上限约6GB，CPUQuota200%，MemoryMax8G。',
          'v12：3组各2000步，随机负例、现网排序KL蒸馏、蒸馏+低权重困难负例。',
          '训练输入沿用2656780条严格train前缀；冻结商品/查询/BGE，仅更新用户MLP，lr2e-6。',
          '蒸馏教师取同一前缀的旧历史，在4096旧商品矿池取64项，排除已看商品；无旧历史不参与。',
          'v13：2组各2000步，增加32维协同商品/用户分量；文本用户、商品、查询均冻结。',
          '比较随机与降权困难负例，协同权重0.01/0.03/0.05/0.15/0.30在开发集选择；',
          '查询协同分量为零，商品两个分量保持单位范数，因此查询文本排序理论保持不变。',
          '两轮均没有训练检查点稳定满足全部未来开发约束，没有浪费资源继续失败配置的全遍历。',
          f'v12冻结选择：{v12["selected"]}；v13冻结选择：{v13["selected"]}，alpha={v13["alpha"]}。',
          '协同分量在部分群体提高MRR，但在较早未来短历史群体仍退步，未作为上线模型。',
          '训练重启只停止自己的单元，保留500步断点与已完成对照。没有停止其他GPU任务。','',
          '新数据与验证：',
          'v12找到3739名此前未评估的用户，1000开发、2739封存；331名有>=3项已知历史。',
          '使用test开始之前的train+valid历史预测test首个正事件，valid事件仅用作当时可见历史，不进入梯度。',
          'v13滚动未来：500开发、3000封存；v14另500开发、3000独立封存，用户集合互斥。',
          '滚动评测在已知历史>=2后预测下一正事件，严格不使用目标同时间或未来事件作为历史。',
          '较早test正事件可以作为之后目标的已发生历史；它们没有成为训练目标。',
          'v14固定保护10项的规则和验收门槛在开发评测前记录；通过六开发群体后冻结，再只打开新封存一次。','',
          '历史回归（1632用户，已反复使用，只作回归，不是独立泛化证据）：',
          '模型 / Top10命中 / Top100命中 / MRR']
    for n,key in [('online_actual','test/old_catalog'),('online_expanded','test/expanded_full_history'),('candidate','test/expanded_full_history')]:
        m=final['models'][n][key]['metrics'];text.append(f'{n} / {round(m["hit@10"]*m["count"])} / {round(m["hit@100"]*m["count"])} / {m["mrr"]:.8f}')
    text+=['','新滚动封存（3000用户，在路线冻结后打开）：','路线 / Hit10 / Hit100 / MRR']
    for n in ['online_actual','online_expanded','initial','candidate']:
        m=result['sealed'][n]['sealed_future']['metrics'];text.append(f'{n} / {m["hit@10"]:.4%} / {m["hit@100"]:.4%} / {m["mrr"]:.8f}')
    text+=['相对实际旧库：MRR提升14.47%；Top100从167人增加到186人；Top10从50人增加到53人。',
           '相对没有保护的原始新三塔，组合在本新封存上的MRR降低约5.57%，换取旧头部回归保护。',
           '不能把组合路线收益说成新用户MLP或协同训练单独带来的提升。','',
           '按用户配对的MRR差值区间：',json.dumps(evidence,ensure_ascii=False),
           '这是离线点估计与未经模型选择校正的区间，不能宣称线上CTR/转化提升。','',
           '工程验收：128条用户/128条查询CPU前向一致性通过，最大误差约2.03e-7。',
           '9项Java单测通过，包含真实Spring容器环境装配和旧/新两个HTTP依赖；旧配置默认关闭保护。',
           '相对原服务包只保留Milvus ef配置补丁、替换双塔装配类、新增头部保护类；其余jar条目保留。',
           'ANN ef4096平均Top100重叠99.94%，最差99%；旧保护Top10在62条可用查询上全部复现。',
           '实际Java内部召回在8账号逐项复现400项保护路线：10旧+390新；切换后在真实18213又验证8账号。',
           '首页6次、语义10种需求各6件、8账号并发、主用户塔故障、查询塔故障、兼容教师故障均通过。',
           '兼容教师故障使用单独故障容器指向不可用地址，绝不停止仍为现网提供保护的旧18120运行时。',
           '隔离8并发P95：现网基线2874ms，候选3043ms；双模型+双索引路线HTTP P95约58.68ms。',
           '标题关键词代理检查56/60，旧基线54/60；该代理不等于完整人工相关性评价。',
           '综合19项发布检查全部通过。独立模型定义、严格权重加载、封存哈希、冻结前时间和服务包SHA均已核对。','',
           '发布结果：'+deployment['state'],
           '主模型：'+deployment['model_key'],'新集合别名：'+deployment['collection'],
           '推荐服务18213，主CPU运行时18132；旧模型CPU运行时18120继续服务保护。',
           '经过网关18288回放6次主页和10种语义请求后标记部署验证通过；GPU2训练任务已结束。',
           '原推荐容器保留为：'+deployment['backup_container'],
           '回滚命令：'+deployment['rollback_command'],
           '上线之后禁止再执行隔离故障门槛脚本；脚本检查live容器是否仍为原快照，否则提前拒绝故障注入。','',
           '限制：数据是评分评论正序列，非完成购买事件；元数据与候选为既有train快照。',
           '滚动新封存主要覆盖短历史，长历史仍主要依赖重复使用的历史回归。',
           '查询回归344条合成查询已经多轮使用；本轮查询/商品张量及路线严格相同，因此复用原记录。',
           '门户可用、离线指标和接口回放已验证；真实用户线上收益仍需实际推荐交付与反馈验证。','',
           '证据目录：'+str(ROOT),
           'selection.json、experiment_policy.json、final_validation.json、results.json、serving_gate.json、',
           'ann_verification.json、guard_ann_verification.json、actual_java_live_route_replay.json、',
           'deployment_build.json、final_artifact_audit.json、deployment_status.json、gateway_replay.json。']
    (ROOT/'RESULTS.txt').write_text('\n'.join(text)+'\n',encoding='utf-8')
    (ROOT/'task_status.json').write_text(json.dumps({'state':'DEPLOYED_VERIFIED','training_complete':True,'model':deployment['model_key'],
        'primary_share':.65,'protected_head_count':10,'candidate_count':763080,'release_checks':'PASS','gateway_replay':'PASS','timestamp':time.time()},indent=2))
    print('FINAL_REPORT_READY_DEPLOYED')

if __name__=='__main__':main()
