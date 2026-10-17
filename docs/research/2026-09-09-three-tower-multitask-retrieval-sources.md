# 语义召回、用户塔与 Item 塔联合训练：三塔资料笔记

检索日期：2026-09-09。仅引用论文原文、作者代码和数据集官网；本次不启动训练，不下载数据。本文补充已有共享 Item Tower 调研，重新核对原始来源，不沿用旧文献表中的未经核验引用。

## 结论与术语边界

可以把目标明确为 **Query 语义塔 + User/History 塔 + 共享 Item 塔**，分别优化 query–item 语义检索与 user–item 推荐检索。这是本文建议的最小实验结构，不是某篇论文的原样复现。已有研究分别支持其中的三塔编码、多任务知识共享以及统一商品向量索引，但不能把这些证据合起来宣称已有同一成品模型保证有效。[S&R Foundation 原文](https://arxiv.org/pdf/2309.08939)、[ItemSage 原文](https://arxiv.org/html/2205.11728v1)

三种含义要区分：

| “第三塔”是什么 | 实际问题 | 资料对应 |
| --- | --- | --- |
| 真实搜索 query 的编码器 | 搜索召回与无 query 推荐联合训练 | S&R Foundation 的输入最贴近，但其最终模型用于分类/排序；ItemSage 的统一索引最贴近召回部署。 |
| 用户历史推断出的语义意图编码器 | 用语义增强 zero-query 推荐 | RGAlign-Rec 直接使用此结构，但其候选是客服意图。 |
| 商品内容编码器，另保留协同 Item ID 表示 | 内容和协同表征融合、冷启动 | UniSRec 可借鉴文本迁移；它不等于新增真实 query 搜索任务。 |

上表依据下列原始文献；匹配等级是本文的比较判断。只把文本特征输入现有 Item 塔，并不自然产生第二个监督任务或第三个请求编码器。

## 六篇优先资料

### 1. ItemSage：共享商品向量及单一索引的直接工业参考

**ItemSage: Learning Product Embeddings for Shopping Recommendations at Pinterest，KDD 2022。** §3.5 混合不同场景、行为的正例训练商品表示；§3.6 明确 Home、Closeup、Search 复用一个 HNSW 索引。适合借鉴共享 Item 表示、任务 batch 配比和离线建库。边界：§2.3 的 PinSage/SearchSage 在训练 ItemSage 时冻结，Home 用历史聚类中的代表 pin 发起检索，并非三个编码器全部端到端联合训练。[论文及全文](https://arxiv.org/html/2205.11728v1)

**匹配等级：召回部署直接匹配；用户塔结构部分匹配。**

### 2. S&R Foundation：确有 User、Query、Item 三塔，但输出是排序任务

**An Unified Search and Recommendation Foundation Model for Cold-Start Scenario，CIKM 2023。** §2.2.1 明确三塔；§2.2.3 拼接三塔表示，输入 Domain Adaptive MTL；§2.2.4 优化 `Lctr + Lsim + Lreg`。推荐场景使用默认空 query 表示。可借鉴语义相关性与行为目标联合学习、文本/ID/稀疏特征融合。其交叉预测头不能原样替代独立向量内积的 ANN 召回。[论文 PDF，§2.2](https://arxiv.org/pdf/2309.08939)

**匹配等级：三塔和多任务结构直接匹配；ANN 召回不直接匹配。**

### 3. RGAlign-Rec：语义意图塔加在用户与候选塔之间

**RGAlign-Rec: Ranking-Guided Alignment for Latent Query Reasoning in Recommendation Systems，2026 年 arXiv 预印本。** §3.3 的 QE-Rec 包含 User、Query、Intent 三塔，得分为用户–意图与 query–意图 cosine 的加权和。query 来自 LLM 对用户上下文的潜在意图推断，候选为客服知识库意图；§4 采用分阶段对齐，不是搜索与推荐两个检索 loss 的联合实验。[论文全文，§3.3–4](https://arxiv.org/html/2602.12968v1)

**匹配等级：语义增强三塔直接匹配；真实搜索 query、商品召回、双任务训练仅可借鉴。**

### 4. UnifiedSSR：搜索推荐联合行为建模与可读代码

**UnifiedSSR: A Unified Framework of Sequential Search and Recommendation，WWW 2024，预印本 2023。** 用商品历史和 query 历史双分支编码搜索行为，推荐关闭 query 分支，通过参数共享连接两场景，并加入意图 session 自监督。适合研究历史序列如何跨场景共享，不应简化成标准共享 Item ANN 三塔。[论文](https://arxiv.org/abs/2310.13921)

作者 PyTorch 仓库包含预训练、微调和评估入口；README 区分搜索与推荐微调模型，所以复现实验时应分清“联合预训练”与“最终同一 checkpoint 服务两个任务”。[作者代码](https://github.com/JennyXieJiayi/UnifiedSSR)

**匹配等级：搜索推荐联合学习直接匹配；具体三塔部署部分匹配。**

### 5. UniSRec：当“语义”指商品内容，优先参考这一支

**Towards Universal Sequence Representation Learning for Recommender Systems，KDD 2022。** 利用商品描述文本、轻量适配器及对比预训练，学习可迁移的商品与序列表示。可借鉴文本表征与推荐监督的连接；论文解决的是序列推荐迁移，不含真实 query 搜索任务，不能称为搜索推荐三塔联合训练。[论文](https://arxiv.org/abs/2206.05941)、[官方 PyTorch 实现](https://github.com/RUCAIBox/UniSRec)

**匹配等级：语义内容增强、冷启动参考；三塔任务不直接匹配。**

### 6. KuaiSAR：让“搜索+推荐联合训练”有可验证的真实数据

**KuaiSAR: A Unified Search And Recommendation Dataset，CIKM 2023。** 提供真实搜索和推荐行为及两场景之间的切换，适合验证搜推联合建模；它是数据集而非三塔算法。官网包含字段说明、两个版本和下载入口。需要进一步核查发布字段的匿名化方式，不能仅凭“query keywords”就假定可以直接用自然语言预训练模型编码原始中文 query。[论文](https://arxiv.org/abs/2306.07705)、[官方数据页](https://kuaisar.github.io/)

**匹配等级：联合训练数据直接匹配；商品领域与自然语言可用性需另核对。**

## 从资料推导出的最小方案

以下为工程建议及数学推导，不是上述任意一篇论文的实验结论。出发点是 ItemSage 的共享候选向量和 S&R Foundation 的三类输入；让 Item 编码保持不依赖当前 query/user，便于离线建索引。[ItemSage](https://arxiv.org/html/2205.11728v1)、[S&R Foundation](https://arxiv.org/pdf/2309.08939)

```text
query_text                 -> QueryTower -> q --- L_search ---+
                                                             |
user_id + history_before_t -> UserTower  -> u --- L_rec ------ ItemTower(item) -> v
```

```text
L_total = lambda_search * L_retrieval(q, v)
        + lambda_rec    * L_retrieval(u, v)
```

建议以两个检索目标起步，分别管理样本、负例和验证指标；新增行为权重、蒸馏、对齐 loss 时逐个消融。三塔是网络数量，两个 loss 是任务定义，二者无需数量相同。任务系数与各任务 batch 频率共同决定实际训练占比，不能只看 loss 前面的系数。任务 batch 混合的参考是 ItemSage §3.5；这里的双 loss 写法和消融顺序为本文建议。[ItemSage §3.5](https://arxiv.org/html/2205.11728v1#S3.SS5)

如果需要个性化搜索，可额外采用请求侧融合 `r = a*q + (1-a)*u`，再计算 `r^T v`。在向量归一化、且 `a` 不依赖候选 item 时，线性性保证它等于两项内积的加权和，仍可查询同一个向量索引。RGAlign-Rec 式加权 cosine 提供结构启发；此 ANN 等价条件为本文数学推导，并非该论文声称的部署结果。[RGAlign-Rec §3.3](https://arxiv.org/html/2602.12968v1#S3.SS3)

## 需要在项目内回答的问题

1. “语义塔”输入究竟是真实 query、用户历史摘要，还是商品文本？三者决定不同的数据契约。
2. 是否有真实 `query -> item` 相关性标签或搜索行为？只有商品文本和用户反馈，可以做内容增强推荐或代理语义目标；代理任务结果不能充当真实搜索收益。
3. 是否要求最终共用一个 item 索引？若要求，最终 item 表示与相似度必须兼容两个请求塔，并分别检验搜索和推荐的 Recall@K/NDCG@K。ItemSage 是可直接参考的统一索引证据。[ItemSage §3.6](https://arxiv.org/html/2205.11728v1#S3.SS6)

推荐阅读顺序：**ItemSage（部署目标）→ S&R Foundation（三塔多任务）→ RGAlign-Rec（语义第三塔）→ UnifiedSSR（联合序列代码）**。若没有真实搜索日志，先看 **UniSRec** 的内容增强路线，再评估 **KuaiSAR** 是否满足真实搜推验证需求。这是基于上述适用边界的选型建议，不预先承诺联合模型优于两个独立模型。
