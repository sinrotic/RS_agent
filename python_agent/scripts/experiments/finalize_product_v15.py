"""按真实训练和验收结果生成中文报告；失败不宣称发布或线上收益。"""
import json,time
from pathlib import Path
import numpy as np
ROOT=Path('/mnt/data/luo/remote_runs/product_v15_training')

def read(name):return json.loads((ROOT/name).read_text())

def interval(before,after):
    def rr(values):
        a=np.asarray(values,dtype='float64');return np.divide(1,a,out=np.zeros_like(a),where=a>0)
    delta=rr(after)-rr(before);rng=np.random.default_rng(20261013)
    boot=[float(rng.choice(delta,len(delta),replace=True).mean()) for _ in range(2000)]
    return {'mrr_delta':float(delta.mean()),'paired_ci95':np.quantile(boot,[.025,.975]).tolist(),'selection_adjusted':False}

def main():
    result=read('results.json');final=read('final_validation.json');selection=read('selection.json');progress=read('release_progress.json')
    assert result['state']=='COMPLETE' and read('qwen_restore_status.json')['state']=='RESTORED_HEALTHY'
    deployed=progress['state']=='DEPLOYED_VERIFIED'
    if deployed:assert read('deployment_status.json')['state']=='DEPLOYED_VERIFIED' and read('serving_gate.json')['state']=='PASS'
    evidence={key:interval(final['initial_pure'][key]['ranks'],final['candidate'][key]['ranks']) for key in ['historical','sealed_future']}
    (ROOT/'paired_mrr_evidence.json').write_text(json.dumps(evidence,indent=2))
    text=['商品三塔完整联合训练与单模型验收（2026-10-13）','',
          '结果：'+('已作为核心主召回上线，旧模型保护位为零。' if deployed else '完整训练完成，但验收未通过，现网保持原版本。'),
          '训练：2656780条严格train前缀正事件，每轮完整无重复遍历，完成3轮，共7970340次推荐样本曝光。',
          '每轮20757个batch128推荐步，合计62271步；每10步交替一次语义训练，共6227语义步。',
          '语义训练只使用2848条训练查询，347条开发查询参与开发选型，344条已用测试查询仅做回归。',
          '保留BGE-M3冻结编码器，商品/用户/查询三个独立残差MLP全部训练，输出1024维单位向量。',
          '残差MLP均1024→256→1024；用户使用当前商品塔编码的最近50件历史，一致性聚合温度0.15，<=2项均值。',
          '没有用户ID嵌入；用户和查询不共享MLP。推荐步更新商品+用户，语义步更新商品+查询。',
          '三塔共享商品空间，使用正商品+127未观测随机负商品的对比损失，加起始纯三塔轻量KL/表示约束。',
          '负例排除整个训练期已知正历史、6个空商品、与目标同文本商品；未观测不等于真实不喜欢。',
          'item/user/query基础学习率分别1e-7/2e-7/1e-6，500步warmup、cosine到20%；语义权重0.1。',
          '从已有良好纯三塔权重继续训练，约束教师是起始纯三塔，不是旧v4头部保护模型。',
          '只从完成整轮的epoch1/2/3按开发集选型，不依据封存指标更换模型。',
          '选中：'+selection['selected']+'；预算完成3轮，导出权重对应所选epoch，不等于强制使用最后epoch。','',
          'GPU：初始GPU2，保存第8000步后按用户要求迁移到GPU1 RTX4090；顺序/RNG/优化器断点恢复。',
          '仅暂停GPU1的Qwen3.5-4B/vLLM 18082，保留BGE与现网推荐；未停止其他用户任务。',
          '训练单元ExecStopPost自动恢复Qwen，恢复健康检查：'+read('qwen_restore_status.json')['state'],
          '训练显存实际峰值：'+str(result['peak_cuda_gib'])+' GiB；旧服务在训练期间不切换。','',
          '推荐验收：路线 / 用户数 / Top10命中人数 / Top100命中人数 / MRR']
    for key in ['historical','sealed_future']:
        text.append(key+'：')
        for name in ['candidate','initial_pure','current_guarded','old_small_catalog']:
            m=final[name][key]['metrics'];text.append(f'{name} / {m["count"]} / {round(m["count"]*m["hit@10"])} / {round(m["count"]*m["hit@100"])} / {m["mrr"]:.8f}')
    if selection.get('selection_correction'):
        text+=['','选型纠错：浮点88/347-2/347略大于86/347，原实现错误淘汰恰好少2条查询的epoch1/2。',
               '整数命中门槛恢复原开发规则后选择epoch1；没有读取/使用封存指标做该选择。',
               '原训练曾为epoch3计算同一1890封存；本报告是纠错后重放复核，不称全新第二封存或只打开一次。',
               '原冻结、结果、审计档案以_before_boundary_correction.json保留。']
    text+=['','冻结效果检查：'+final['state'],json.dumps(final['checks'],ensure_ascii=False),
           '预定发布门槛对照起始纯三塔：新封存MRR>=95%、Hit10>=90%、Hit100>=98%；历史MRR>=95%、Hit10不低于起始纯三塔。',
           '用户明确取消旧保护，未沿用旧模型18人的零退步门槛；现网带保护只作同群体对照。','',
           '语义回归（已用344合成查询，非人工或独立线上相关性验证）：']
    for name,v in final['semantic'].items():text.append(name+'：'+json.dumps(v['metrics'],ensure_ascii=False))
    text+=['','按用户配对MRR变化和未经模型选择校正的95%区间：',json.dumps(evidence,ensure_ascii=False),'']
    if deployed:
        d=read('deployment_status.json');text+=['工程验收全部通过：CPU/训练前向一致、1024维HTTP契约、独立新商品索引、ANN与精确Top100对照。',
            'Java11项测试通过；实际Java对8账号逐项复现400件纯新模型召回、旧保护位0、历史80过滤。',
            '主页分页、语义需求、8并发及用户塔/查询塔不可用显式降级均通过；故障仅注入隔离运行时。',
            '服务包只替换双塔装配和新增历史过滤器，其余现网jar条目字节保持。',
            '有效候选763080，新集合：'+d['collection'],'模型：'+d['model_key'],
            'CPU运行时18136、推荐18213；经过网关18288回放和真实18213顺序验收后完成发布。',
            '备份容器：'+d['backup_container'],'回滚：'+d['rollback_command'],
            '保护旧模型运行时仍保留作回滚，但新版单模型路线不会调用它。','']
    else:text+=['未发布：'+progress['state']+'。保留当前现网，训练完成不代表模型质量达标。','']
    text+=['限制：样本是评论评分正序列，不是完成购买；候选与元数据来自既有train快照。',
           '1890新封存为此前未评估用户的未来事件，其训练前缀可能被已有模型学过；主要覆盖短历史。',
           '历史1632和语义344已多轮使用，只作回归，不能说是独立泛化结果。',
           '离线、接口与工程可用不等于真实线上CTR/购买转化提升，需要真实推荐交付和反馈验证。',
           '证据目录：'+str(ROOT)]
    (ROOT/'RESULTS.txt').write_text('\n'.join(text)+'\n',encoding='utf-8')
    (ROOT/'task_status.json').write_text(json.dumps({'state':progress['state'],'training_complete':True,'selected':selection['selected'],
        'full_epochs_completed':3,'old_head_protection_requested':0,'release_quality':final['state'],'timestamp':time.time()},indent=2))
    print('V15_REPORT_READY',progress['state'],flush=True)

if __name__=='__main__':main()
