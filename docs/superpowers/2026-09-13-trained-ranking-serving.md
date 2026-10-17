# 已训练排序主链路接入记录

复用 `/home/luo/RS_agent_remote/outputs/ranking/cold_full_formal_20260620_existing_deepfm/` 中的模型，未重新训练。两份产物均记录 45,655,785 个训练样本、5 个 epoch。COLD 是仓库实现的 pointwise logistic 粗排器；DeepFM 使用线性项、4 维 FM 因子和 4 个隐藏单元，不应描述为大规模深度排序网络。

六个输入为用户／商品是否有训练历史，以及商品正向事件数、商品正向用户数、用户不同商品数、用户正向事件数的 log1p。特征从原 train 的 11,538,991 条事件中提取 9,131,157 条正向事件，覆盖 5,375,378 个用户、762,622 个商品；快照截止时间为 `1684108779231`，没有引入 validation/test。它是训练结束时的在线快照，不等同于每个训练样本的历史前缀，也不会自动随在线反馈更新。

首页多路召回最多 500 个候选，COLD 粗排至 200，DeepFM 精排至 96，最后结合相关性、反馈和多样性展示。显式保留当前批次、探索和语义候选的配额，仍对这些候选计算真实模型分数。查询存在时使用 `0.3 × sigmoid(DeepFM logit) + 0.7 × BGE`，无查询使用 DeepFM 分数；这两个融合权重属于工程策略，sigmoid 分数不是校准后的点击概率。

对话语义召回经过相同模型排序后交付，先应用价格硬约束；`/agent/recommend/rerank` 只重排传入 ID。语义交付现在可通过 request_id 记录反馈归因。profile/cold 路径复用首页排序。当前文本对话仍以语义召回为入口，不代表所有 Agent 意图路由和多轮约束继承均已补齐。

CPU 运行时为 `172.21.0.1:18119`，systemd user 服务为 `rs-trained-ranking-runtime.service`，目录为 `/home/luo/RS_agent_java/data/models/cold_deepfm_20260914`。`20260914` 是发布版本标识。开关 `RS_RECOMMEND_TRAINED_RANKING_ENABLED=true`；运行时不可用时首页和对话回退 BGE，并记录 `trained_ranking_unavailable`，不会保留假的 DeepFM 来源标签。对话内部响应和 trace 暴露降级，现有 Agent 前端适配器尚未展示该新增字段。

验证结果：Java 94 项测试通过；独立扫描训练集验证 25 组统计，126 组模型分数与原推理函数误差均为 0；16 个画像的首页换批和实际阶段统计通过，真实样例为 480→200→96→6。对话排序、仅已有候选重排、交付反馈、价格过滤和故障回退通过。六路召回进入候选池并不保证每一路都进入最终六个展示位，本次样本的强 ItemCF、UserCF 最终展示计数为零。

仅发布 Recommend JAR，SHA256 为 `55adc7c54b1513232985783a50afb638866ce67955d5dac571b79343961f2b87`。备份位于 `/home/luo/RS_agent_java/backups/20260914-ranking`，含旧 JAR、Compose、环境配置及版本清单；部署脚本遇到失败自动恢复。手工回退时停止 Recommend，恢复这些文件，再仅重建 Recommend。原模型 diagnostic 标记和效果门禁保持原值，尚无新的离线排序效果或线上 A/B 提升结论。

验证材料：

- [模型及特征清单](evidence/2026-09-13-trained-ranking-manifest.json)
- [原推理函数一致性](evidence/2026-09-13-trained-ranking-inference.json)
- [接口验收](evidence/2026-09-13-trained-ranking-acceptance.json)
- [发布核验](evidence/2026-09-13-trained-ranking-deployment.json)
- [浏览器验收](evidence/2026-09-13-trained-ranking-browser.json)
- [最终版本线上粗排与精排实测](evidence/2026-09-13-trained-ranking-live-stages.json)

浏览器实测首页三批共 18 个不同商品、喜欢／不感兴趣、普通聊天、SSE 和两轮查询均通过。线上对话真实阶段为 100→100→96→5，无降级。单商品 fine_rank 表示保留后的 DeepFM 顺序；模型未返回完整粗排名次，coarse_rank 留空，阶段总数仍完整记录。

最终部署完成于 2026-09-14，跨日之前开始的验收材料保留 2026-09-13 文件名。名次记录修正后重新通过 94 项测试及完整接口验收，再发布最终 JAR；此次补丁的上一版本备份为 `/home/luo/RS_agent_java/backups/20260914-ranking-final`，需要退回接入排序之前的版本时使用前文的原始备份。
