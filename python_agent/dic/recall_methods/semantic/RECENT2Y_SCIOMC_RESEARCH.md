# semantic recent-2y SciOMC 调研

日期：2026-06-03

## 1. 调研目标

本调研服务于 pool500 recent-2y `semantic` 单方法重建。目标不是复用旧 full-data 语义产物，而是在 train-only governance 下重新确定：文本字段组织、索引/检索策略、smoke/formal 数据集契约、artifact manifest、评估口径和晋升门禁。

当前约束：候选生成和 source artifact 构建只能读取 recent-2y train-visible 输入；不得使用 holdout/valid/test/LOPO/oracle/eval label；smoke 只做程序和 schema 验证；formal 才能作为正式效果证据。

## 2. 论文与工业实践要点

### 2.1 序列历史可以作为语义召回 seed，但不能被单一兴趣向量稀释

- SASRec（Self-Attentive Sequential Recommendation）说明用户近期行为序列可以通过注意力机制捕获局部/长期兴趣，支持“用最近 train-only seed item 查询候选”的思路。对本项目的落点是：`semantic` 不应只用全局用户画像，而应保留最近正反馈 item 作为 query seeds，并记录 `seed_window`。
- MIND（Multi-Interest Network with Dynamic Routing）与 PinnerSage 的多兴趣/多簇实践都表明，用户历史常包含多个意图，召回阶段用多个兴趣 seed 比单一向量更稳。对本项目的落点是：formal 应按用户历史 item 多 seed 检索，避免把 mixed interests 合并成一个不可解释查询。

### 2.2 metadata 语义召回应优先可审计，dense/hybrid 作为后续增强

- Sentence-BERT 与 DPR 证明 dense embedding 能捕获同义、语义相近关系，适合 title/description/attribute 的近邻召回。
- ColBERT 和 ANCE 进一步说明 dense/late-interaction/ANN 检索可提升质量，但需要预计算向量、ANN index、负采样或 hard-negative 训练，治理和资源成本高于 token/BM25。
- S3-Rec 表明 item attribute 与序列上下文可以通过自监督预训练融合，适合后续把 metadata 与行为序列共同学习。

对当前 `semantic` 的选择：第一版 recent-2y 重建采用 **train-only metadata token overlap / full_metadata_overlap** 作为可解释、轻资源、易审计基线；不在本轮直接上 dense embedding 或 ANN。若后续转 dense/hybrid，需要单独记录 encoder checkpoint、tokenizer/hash、训练输入、负采样、index 参数和远程复现证据。

### 2.3 BM25 / token overlap / dense / hybrid 的取舍

| 策略 | 优点 | 风险 | 本轮取舍 |
|---|---|---|---|
| token overlap / metadata overlap | 可解释、低资源、容易做 no-holdout audit | 依赖字段清洗；同义词弱；可能偏向热门词 | 作为 `semantic` recent-2y 第一版 source artifact |
| BM25 / IDF | 比简单 overlap 更能抑制泛词 | 需要 corpus 统计和参数记录 | 可作为下一步 scorer 增强，当前先记录 blocker |
| dense embedding | 语义泛化强，适合 synonym/description | 训练/编码/ANN 重资源；解释弱；漂移和治理成本高 | 本轮不作为晋升依据 |
| hybrid sparse+dense | 兼顾可解释与语义泛化 | 需要融合/重排门禁和 overlap 评估 | 后续 RAG/semantic v2 方向 |

## 3. 字段组织建议

`semantic` 文档应由静态 item metadata 组织，字段分层如下：

1. **强身份字段**：`title_clean`、`parent_asin`（仅作 id，不作 token 扩展）、brand/model/spec。需要保留型号、容量、尺寸、兼容性词，不能粗暴去数字。
2. **约束字段**：`main_category`、`category`、`categories_flat`。用于减少语义漂移，避免“相同泛词跨大类乱召回”。
3. **弱语义字段**：`description_text`、`features_text`、`item_text`、`store`、`brand`。用于补充 token，但需要 stop words 和字段权重控制。
4. **禁止字段**：评估 label、holdout/test 统计、LOPO 命中、oracle 诊断、pool1000 输出、旧 full-data derived source index。

字段清洗原则：

- 保留品牌、型号、规格、接口、容量等可区分商品的 token。
- 去除极泛词和平台词，但不要把 category 层级完全抹掉。
- manifest 中记录字段列表、stop words/过滤策略、`selection_mode`、`seed_window`、`per_user`、`per_token_item_limit` 等参数。

## 4. smoke/formal 数据集设计

### smoke

用途：只验证代码路径、schema、manifest、no-holdout gate、候选非零。

建议契约：

- 输入：recent-2y `manifest.json`、`recall_views/manifest.json`、`train_only_governance/manifest.json`、smoke eligible manifest。
- 用户：约 200 人，覆盖 `collaborative_rich`、`sequence_sufficient`、`fallback_only`、少量有 seed 的 `cold_start`。
- 参数：`limit_users=200`、`seed_window=20`、`per_user=80`、`per_token_item_limit=1000`、`max_candidate_items=30000`。
- 输出：七件套 + `semantic_input_dataset.jsonl`，manifest 标注 `promotion_allowed=false`。

### formal

用途：作为 recent-2y `semantic` 正式方法 artifact 和评估输入，但不自动晋升 READY。

建议契约：

- 输入仍只来自 train-visible。
- 用户：formal eligible manifest 约 50k 用户，覆盖 `collaborative_rich`、`sequence_sufficient`、`fallback_only`；`medium_behavior` 仅 audit-only。
- 参数：`limit_users=50000`、`seed_window=50`、`per_user=120`、`per_token_item_limit=2000`、`max_candidate_items=200000`。
- formal 不是“无限制全量”，而是一个可复核、资源受控的 target-slice formal；若需要全量 semantic，另起重资源/远程计划。

## 5. source artifact manifest 必备字段

`source_index_manifest.json` 与 `method_dataset_manifest.json` 至少应记录：

- `source=semantic`、`canonical_source=semantic`，不得冒充 `semantic_title_category_expansion`。
- `source_status=TARGET_SLICE_DIAGNOSTIC`。
- 输入路径、hash、`train_only=true`、forbidden scopes audit。
- `candidate_generation_allowed=false`、`ranking_input_replacement_allowed=false`、`pool1000_allowed=false`、`promotion_allowed=false`。
- `candidate_row_count`、`user_coverage_count`、candidate count 分位数、seed item metadata coverage、semantic index record count。
- 构建参数：`selection_mode`、`seed_window`、`per_user`、`per_token_item_limit`、`max_candidate_items`。
- 若后续引入 dense/hybrid，必须额外记录 encoder/checkpoint/tokenizer/index 参数和远程复现信息。

## 6. 评估建议

formal 评估阶段允许读取 eval label 计算指标，但 eval label 不得反向进入 candidate generation/source index。建议报告：

- Recall@20/50/100/500、HitRate@K。
- user coverage、candidate row count、candidate_count p50/p90/max。
- 用户桶分层：collaborative_rich、sequence_sufficient、fallback_only；cold_start 仅解释性审计。
- 与 READY source 的 source overlap / unique contribution，尤其是相对 `category`、`popular`、`swing_recall` 的新增覆盖。
- undercoverage：空候选用户数、低于 per_user 的用户数、主要原因（无 seed metadata、token 太泛、category 缺失等）。

## 7. 失败模式与 gate

| 失败模式 | 证据 | gate 处理 |
|---|---|---|
| formal 候选为空或覆盖低 | `candidate_row_count=0`、`user_coverage_count` 低 | 保持 DEFERRED/DIAGNOSTIC_ONLY |
| 旧 artifact 回流 | manifest 路径含 full_lightweight、clean_10000、pool1000 | no-holdout audit BLOCKED，禁止晋升 |
| 语义漂移 | category mismatch 高、overlap 全靠泛词 | 不进入主路，改进字段权重/stop words |
| 资源成本不可控 | runtime/磁盘/内存异常，缺少远程复现 | 不做 full formal，转远程/分片 |
| 互补性不足 | 与 category/popular 高 overlap，Recall 无增益 | 不硬并主路，记录 blocker |

## 8. 对本仓库的落地结论

1. 当前 `semantic` 应作为 **target-slice diagnostic metadata recall** 先产出 recent-2y smoke/formal artifact。
2. 本轮先采用 `full_metadata_overlap`，不直接上 dense/ANN；dense/hybrid 写为后续 v2。
3. `source_config.yaml` formal tier 不能保留可被 builder 解释成 0 的数量参数，应改为非零的 50k target-slice formal 参数。
4. formal 成功不等于 READY；只有在 Recall、覆盖、互补性、route gate 证据充分时，才能建议进入全局主路收口。

## 参考论文 / 资料

- Kang & McAuley, 2018, SASRec: Self-Attentive Sequential Recommendation — https://arxiv.org/abs/1808.09781
- Cen et al., 2019, MIND: Multi-Interest Network with Dynamic Routing for Recommendation at Tmall — https://arxiv.org/abs/1904.08030
- Pal et al., 2020, PinnerSage: Multi-Modal User Embedding Framework for Recommendations at Pinterest — https://arxiv.org/abs/2007.03634
- Reimers & Gurevych, 2019, Sentence-BERT — https://arxiv.org/abs/1908.10084
- Karpukhin et al., 2020, Dense Passage Retrieval — https://arxiv.org/abs/2004.04906
- Khattab & Zaharia, 2020, ColBERT — https://arxiv.org/abs/2004.12832
- Xiong et al., 2020, ANCE — https://arxiv.org/abs/2007.00808
- Zhou et al., 2020, S3-Rec — https://arxiv.org/abs/2008.07873
