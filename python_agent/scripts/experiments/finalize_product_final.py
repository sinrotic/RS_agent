"""记录最终稳定单三塔的真实来源、实际部署、比较数据与回滚。"""
import json,time
from package_product_final import ROOT,digest,write

def read(name):return json.loads((ROOT/name).read_text())

def main():
    d=read('deployment_status.json');gate=read('serving_gate.json');v=read('final_validation.json');m=read('export/manifest.json')
    assert d['state']=='DEPLOYED_VERIFIED' and gate['state']=='PASS'
    assert read('gateway_replay.json')['state']==read('actual_java_live_route_replay.json')['state']=='PASS'
    ann=read('ann_verification.json');replay=read('concurrency_replay.json');offline=read('export/runtime_replay.json')
    text=['商品三塔最终服务方案 v1（2026-10-13）','',
        '结论：冻结并上线当前更稳定的已训练纯三塔，旧模型保护位为0，保留三个塔。',
        '本发布是模型选定、版本化导出与服务接入，不是新增训练，不把失败的v15全量续训标成通过。',
        '模型：'+d['model_key'],'候选库：763080件有效目录商品，1024维单位向量。',
        'BGE-M3固定编码；商品、用户、查询为三个独立1024→256→1024残差MLP。',
        '商品向量离线编码；用户聚合最近50项可用商品向量，平均互相余弦支持度softmax温度0.15。',
        '两项或更少历史用均值；没有ID嵌入或额外协同分量；查询使用BGE+独立查询残差。',
        '模型全部张量与先前稳定纯三塔严格一致，商品矩阵/ID/定义文件SHA一致；仅赋予最终服务版本。',
        '真实训练来源：'+m['source_checkpoint'],json.dumps(m['source_training_config'],ensure_ascii=False),
        '原来源模型SHA：'+m['source_model_sha256'],'最终模型SHA：'+m['output_hashes']['model.pt'],'',
        '核心召回：一个用户塔HTTP、一个三塔商品索引，历史80件排除、去重，不调用旧保护模型。',
        '主召回保留兴趣预算65%，主页回放为270-271项；查询三塔保留原65%主候选比例与BGE补充。',
        '其他召回、排序、商品回填及反馈流程沿用既有服务。旧运行时保留用于备份回滚。','',
        '既有离线证据（都是已评测过的回归/复核，非新增独立验证）：','路线 / 用户数 / MRR / Top10命中人数 / Top100命中人数']
    for key in ['historical','sealed_future']:
        for name in ['candidate','current_guarded','rejected_full_training']:
            s=v[name][key]['metrics'];text.append(f'{key} {name} / {s["count"]} / {s["mrr"]:.8f} / {round(s["count"]*s["hit@10"])} / {round(s["count"]*s["hit@100"])}')
    text+=['','此前3000用户回归：']
    for name,s in v['previous_3000'].items():
        s=s['metrics'];text.append(f'{name} / MRR{s["mrr"]:.8f} / Top10 {round(s["count"]*s["hit@10"])} / Top100 {round(s["count"]*s["hit@100"])}')
    text+=['','最终纯三塔相对当前带保护路线，在近期样本MRR较好；历史Top10由带保护19人变为纯三塔17人。',
        '该取舍与用户明确要求取消保护一致，不宣称所有群体所有指标均提升。',
        'v15续训近期MRR高5.76%，但历史MRR较此最终纯三塔低15.1%、Top10少1人，因此未选。',
        '语义344条已用合成查询：'+json.dumps(v['semantic']['metrics'],ensure_ascii=False),'',
        '实际工程重新验收：',f'CPU前向128用户/128查询，误差 user={offline["user_max_error"]} query={offline["query_max_error"]}。',
        '独立模型定义严格加载、权重/索引哈希、11项Java测试及测试类字节一致通过。',
        f'ANN ef4096，Top100平均重叠{ann["ann_overlap_at100_mean"]:.4%}，最差{ann["ann_overlap_at100_min"]:.4%}。',
        '真实Java内部召回8账号各400件逐项顺序一致，旧保护0位；切换后再次在18213核对。',
        '首页分页、已看商品排除、10种中英文商品需求、8并发、用户塔与查询塔不可用降级均通过。',
        f'8并发P95：基线{replay["baseline"]["p95_ms"]:.2f}ms，最终候选{replay["candidate"]["p95_ms"]:.2f}ms。',
        '全部发布检查：'+json.dumps(gate['checks'],ensure_ascii=False),'',
        '最终集合别名：'+d['collection'],'CPU运行时18138，推荐18213，网关18288。',
        '原服务备份：'+d['backup_container'],'回滚：'+d['rollback_command'],
        'Qwen GPU1/18082全程保持恢复状态；此次发布未暂停或训练GPU任务。','',
        '限制：评分评论正序列不是购买事件；已有历史/语义/封存都已使用过。',
        '这次根据已有结果选择服务版本，离线/接口验证不等于线上CTR或转化提升。',
        '证据目录：'+str(ROOT)]
    (ROOT/'RESULTS.txt').write_text('\n'.join(text)+'\n',encoding='utf-8')
    write('task_status.json',{'state':'DEPLOYED_VERIFIED','model':d['model_key'],'protected_head_count':0,'candidate_count':763080,
        'single_trained_three_tower':True,'release_is_new_training':False,'timestamp':time.time()})
    print('FINAL_MODEL_DEPLOYED_AND_DOCUMENTED',d['model_key'],flush=True)

if __name__=='__main__':main()
