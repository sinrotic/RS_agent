# 搜索与推荐共享 Item Tower 的多任务训练调研

更新时间：2026-08-03
研究对象：搜索与推荐共用商品向量及 ANN 索引，联合利用点击、加购、成交等行为训练。
资料边界：仅使用论文原文、作者/机构官方代码仓库和官方文档。本文没有下载业务数据、安装新依赖或启动训练。

## 结论

“多任务训练的 loss 都是加权求和”是一个可行的**外层写法**，不是充分的设计原则：

```text
L = sum(lambda_s,t * L_s,t) + regularization
```

其中 `s` 是场景（`recommend` 或 `search`），`t` 是监督目标（点击、加购、成交等）。但每个 `L_s,t` 的样本定义、条件概率和负样本必须不同；不能把所有未发生的行为一律作为相同负样本。特别地，召回的 dot-product / sampled-softmax 损失与精排的 CTR/CVR 二分类损失解决的是不同问题。

对本仓库的本地数据，建议先实现一个 **PyTorch 的两请求塔 + 共享 Item Tower**：

```text
推荐请求：User + 场景 + 历史  -> q_rec -------+
                                                  dot / cosine -> 一个 Item ANN 索引
搜索请求：User + Query + 场景 -> q_search ----+
商品：商品 ID + 类目 + 品牌 + 文本等 -> v_item （离线全量计算）
```

先只用“同一次已曝光列表中的点击”训练两个检索损失；再加入成交的辅助检索损失或样本权重。ESMM、MMoE、PLE 更适合在已有稳定检索候选后作为多行为**精排**基线，或作为共享编码层的选择依据。它们本身不自动提供可用于 ANN 的独立 `Item Tower`。

**但这不是当前 Amazon 数据的直接训练配方。**现有清洗代码实际保留的是 `user_id`、`parent_asin`、`rating`、`timestamp`、`verified_purchase` 及商品元数据/文本；没有 `query`、`scene`、`request_id`、曝光集合、位置、点击或真实订单归因。见 [`recall_clean.py`](../../python_agent/rs_core/data/pipelines/recall_clean.py)。因此当前可严谨训练的是“用户历史 -> 下一正反馈商品”的推荐双塔，`rating` 阈值可定义为正反馈，`verified_purchase` 至多可作为更强的**交互强度**或样本权重。当前数据不能证明搜索召回、CTR/CVR、ESMM 或点击/成交多任务效果，也不能把未观察到的商品叫作曝光未点击负例。

## 先澄清几个模型的适用边界

| 模型/资料 | 原始问题与核心机制 | 对本问题的结论 |
| --- | --- | --- |
| [YouTube DNN](https://research.google/pubs/deep-neural-networks-for-youtube-recommendations/) / [论文](https://arxiv.org/abs/1606.07792) | 将候选生成与精排分开；候选生成把用户历史与上下文映射为向量，并以百万级候选的近似 softmax 训练。 | 是“请求向量检索商品向量”的直接起点。搜索请求可视为另一种 request encoder，但论文没有给出“搜索+推荐共用一个 Item Tower”的成品配方。 |
| [ESMM](https://arxiv.org/abs/1804.07931) | 处理 CVR 只在点击样本上可观测造成的样本选择偏差和稀疏性，显式建模 `pCTCVR = pCTR * pCVR`，在整个曝光空间训练 CTR 与 CTCVR。 | 当成交是“点击后才可发生”的漏斗标签时，应优先借鉴其条件概率约束；不应把所有曝光的 `order=0` 当成无条件 CVR 负例。 |
| [MMoE 论文](https://dl.acm.org/doi/10.1145/3219819.3220007) / [官方 DeepRec 示例](https://github.com/alibaba/DeepRec/tree/main/modelzoo/mmoe) | 共享多个 expert，每个任务有自己的 gate 和 tower，缓解任务相关性不同造成的负迁移。官方示例直接以 `clk`、`buy` 为两个标签。 | 适合点击和成交之间已经发生负迁移时的精排 backbone；不是 ANN 召回的替代。 |
| [PLE](https://arxiv.org/abs/2007.07184) / [官方 DeepRec 示例](https://github.com/alibaba/DeepRec/tree/main/modelzoo/ple) | Progressive Layered Extraction 同时保留 task-specific 与 shared experts，目标是减轻多任务负迁移。 | 当搜索与推荐、点击与成交的梯度冲突明显时，可替换共享 request/item 特征编码器；应先用简单共享塔建立可解释基线。 |
| [M3](https://arxiv.org/abs/1902.08588) | M3 是 Multi-temporal-range Mixture Model：以不同时间范围的用户序列编码器加门控，处理短期与长期行为并存。 | 它改善的是 `User`/请求侧序列表示，不是多行为损失或共享 ANN 索引方案。可在最小模型有效后替换 `history encoder`。 |
| [NMTR](https://ieeexplore.ieee.org/document/8731371) | Neural Multi-Task Recommendation from Multi-Behavior Data 按行为依赖做级联预测。 | 对浏览/加购/购买这类顺序清晰的多行为数据是更直接的参考；当前 Amazon 数据缺少这些分阶段行为，不能据此构造其任务链。 |

官方 [TensorFlow Recommenders 多任务教程](https://www.tensorflow.org/recommenders/examples/multitask) 也明确把数据丰富的点击和稀疏的购买作为适合知识迁移的一对任务，并在示例中分别组合 retrieval 与 ranking task。它支持“多个 task loss 加权”，但没有免除上述曝光口径、条件标签和检索可部署性的约束。

## 可复用的损失设计

### 1. ANN 召回主损失：按场景分别构造 request

对有曝光列表的请求 `r`，正样本为点击商品 `i+`，同一请求内曝光但未点击的商品为候选负例集合 `N(r)`。令共享商品向量为 `v(i)`，`q_s(r)` 为场景 `s` 的请求向量，推荐和搜索使用不同 encoder：

```text
score_s(r, i) = q_s(r)^T v(i) / tau
L_retrieval,s = -log exp(score_s(r, i+)) /
                     (exp(score_s(r, i+)) + sum(i in N(r)) exp(score_s(r, i)))
```

实际训练可以把同一 batch 的其他正商品加入 `N(r)`，但应剔除同一用户/请求中已正反馈的商品，避免把真阳性当负例。只有“有曝光列表”时，未点击才是最可靠的行为负例；没有曝光日志时，batch 内或随机负例只能视为弱负例。

```text
L_retrieval = lambda_rec_click * L_retrieval,recommend
            + lambda_search_click * L_retrieval,search
```

两个请求塔输出必须与 `v(i)` 维度相同，且训练和 ANN 使用同一相似度度量。若线上用 cosine，应在训练和建库前都做 L2 normalize；若用 inner product，不能线上临时改成 cosine。

### 当前 Amazon 交互数据的可用替代

令用户在 `t` 前的历史为 `H_u,t`，评分达到现有正反馈阈值的下一个商品为 `i+`。训练样本是：

```text
(user_id, H_u,t, target_item_id=i+, target_timestamp=t,
 rating, verified_purchase, item title/category/text)
```

它可用同样的 sampled-softmax / in-batch-negative 形式训练 `q_rec(user, H_u,t) dot v_item`，但负例只能来自训练时间窗中的“用户未交互商品”或 batch 内商品，须称为**采样弱负例**。推荐先让 `verified_purchase=1` 的正反馈拥有较大样本权重，例如：

```text
L_amazon = mean(w(rating, verified_purchase) * L_retrieval,recommend)
```

这不是 CTR、CVR，也不是两个语义不同任务的多任务学习。它只能回答“共享 Item Tower 的推荐召回是否优于现有单塔/协同过滤基线”。将商品标题文本编码进 `ItemTower` 可同时得到内容语义能力，但这仍不同于已记录的用户搜索 query 召回。

### 2. 成交不是普通的第二个 “0/1” 标签

有严格漏斗关系时可采用 ESMM 式辅助目标。对每个**曝光**样本：

```text
p_ctr = sigmoid(h_ctr(x))
p_cvr = sigmoid(h_cvr(x))
p_ctcvr = p_ctr * p_cvr
L = lambda_ctr * BCE(click, p_ctr)
  + lambda_ctcvr * BCE(click * order, p_ctcvr)
```

这里的 `click * order` 等价于“该曝光最终点击且成交”。`p_cvr` 不直接以所有曝光的 `order` 监督，避免把没有点击因而根本没有成交机会的样本误作 post-click CVR 负例。这是 ESMM 的关键，而非单纯多加一个 `BCE(order, ...)`。

若业务中的“成交”可不经当前点击归因，或标签窗口/归因规则不同，则不要套此乘积；应将其记录为另一个带明确归因窗口的辅助任务，并先做单任务校验。

### 3. 如何把成交信号用于召回

起步阶段二选一即可，避免不稳定的四五个目标同时上线：

1. 保持点击为唯一检索正例，把成交样本在 `L_retrieval` 中乘以较高样本权重 `w_order > 1`，同时保留非成交点击；
2. 在同一共享 `Item Tower` 上增加 `L_retrieval,order`，只从发生成交的请求构造正例，并单独设置较小的 `lambda_order`。

成交样本少时，方案 1 通常更稳。方案 2 仅在每个场景都有足够成交请求、且离线 `Recall@K(order)` 有置信区间改善时保留。`lambda` 不能照搬论文或按样本量倒数硬设：应以验证集的搜索点击召回、推荐点击召回、成交召回三个指标分别观察；某任务下降说明共享空间或权重造成了负迁移。

## 最小可落地方案

### 模型

```text
ItemTower(item_id, category_id, brand_id, title_tokens, price_bucket)
  -> MLP -> v_item[64]

RecommendRequestTower(user_id, recent_item_ids, scene, device, time_bucket)
  -> MLP -> q_rec[64]

SearchRequestTower(user_id, recent_item_ids, query_tokens, scene, device, time_bucket)
  -> MLP -> q_search[64]
```

- 三个输出层均为 64 维，并 L2 normalize；`ItemTower` 只有一份参数。
- 搜索和推荐的 request tower 分开，避免把“当前 query 相关性”与“无 query 的偏好”强行压成相同输入函数。
- 每个 batch 混入两个场景，并以配置的 `lambda_rec_click`、`lambda_search_click` 汇总主损失。单个 batch 没有某场景时，对该场景损失置零，不要伪造标签。
- 先不要加入 MMoE/PLE。第一版目标是证明同一个 `v_item` 能同时提升两条链路的候选覆盖；之后再做“共享底层 Item encoder + 场景专属 item projection + 两个索引”的对照实验。

### 最小样本 schema

建议将事件事实表与商品快照表分开。事件按“一个请求-一个已曝光商品”一行保存；训练时按 `request_id` 聚合成正负集合。

| 字段 | 类型/示例 | 必要性与用途 |
| --- | --- | --- |
| `event_ts`、`request_id`、`user_id` | 时间戳、字符串、字符串 | 严格时间切分、同请求曝光集合、去重；禁止随机切分导致未来泄漏。 |
| `scene` | `search` / `recommend` | 决定使用 `q_search` 或 `q_rec`，并分别评估。 |
| `query_text`、`query_id` | 搜索填值，推荐为空 | 搜索塔输入；空 query 不可伪造为普通 token。 |
| `item_id`、`catalog_version` | 字符串、版本/日期 | 与事件时点一致的商品特征，供共享 Item Tower 使用。 |
| `exposed`、`position`、`recall_channel` | `1`、整数、枚举 | 训练集合只保留真实曝光；用于位置偏置诊断和负例来源审计。 |
| `clicked`、`carted`、`ordered`、`label_window_end` | 0/1、0/1、0/1、时间戳 | 目标和归因窗口；应保存完整漏斗，至少保证 `ordered => clicked` 的口径可检查。 |
| `history_item_ids`、`history_event_ts` | 截断序列 | 只能使用 `event_ts` 之前的行为；搜索与推荐都可复用。 |
| `device`、`region`、`time_bucket` | 类别特征 | 可选请求上下文；先加入稳定且线上可得的字段。 |

商品快照至少包括 `item_id`、`catalog_version`、`title`、`category_id`、`brand_id`、`price_bucket`、`is_available`。离线建索引和线上服务必须过滤下架/无库存商品；该过滤不应依赖模型分数。

当前 Amazon 输入只覆盖其中的 `user_id`、`item_id`、`event_ts`、`rating`、`verified_purchase` 和一部分商品元数据。上述完整 schema 是后续接入线上搜索/推荐日志的目标契约，不能从当前离线交互表推断出来。

### 离线训练、评估和建库顺序

1. 以请求时间做 train/validation/test 三段切分；全部 history 与商品快照截断在该请求发生时。
2. 先运行四个单独指标：`Recall@100(search, click)`、`Recall@100(recommend, click)`、两个对应的 `NDCG@100`；有稳定成交量才增加两个成交口径。不要只汇总一个全局 AUC。
3. 检索训练稳定后，用全量有效商品计算 `v_item`，写出带 `item_id`、`catalog_version`、向量的文件，并重建一个 ANN 索引。
4. 离线分别以 `q_search` 与 `q_rec` 查询同一个索引。若任一场景显著退化，再尝试拆分 item projection/index，而不是先扩大网络。

仓库的 [`python_agent/pyproject.toml`](../../python_agent/pyproject.toml) 已在 `training` extra 中声明 `torch`，并在 `milvus` extra 中声明 `pymilvus`/`milvus-lite`；因此第一版可留在 PyTorch，并使用已有 Milvus 路径承载离线商品向量。没有必要为了第一版同时引入 TensorFlow、DeepRec 和 TorchRec。

## 可本地训练的开源实现选择

| 选择 | 官方证据 | 适合程度 |
| --- | --- | --- |
| 自定义 PyTorch 最小模型 | 本仓库已声明 `torch`；[TorchRec 官方仓库](https://github.com/pytorch/torchrec) 提供 PyTorch 推荐系统的 embedding 与分布式训练组件。 | **首选**：少量/中等规模本地数据时，直接实现上述三塔最容易保证训练目标和 ANN 部署一致。数据或 embedding 表很大后再接 TorchRec。 |
| TensorFlow Recommenders (TFRS) | [官方 retrieval 教程](https://www.tensorflow.org/recommenders/examples/basic_retrieval)、[官方多任务教程](https://www.tensorflow.org/recommenders/examples/multitask)。 | 适合作为可运行的 retrieval + ranking 多任务参考实现；当前仓库未声明 TensorFlow，意味着是新增技术栈。 |
| Alibaba DeepRec ModelZoo | [ESMM](https://github.com/alibaba/DeepRec/tree/main/modelzoo/esmm)、[MMoE](https://github.com/alibaba/DeepRec/tree/main/modelzoo/mmoe)、[PLE](https://github.com/alibaba/DeepRec/tree/main/modelzoo/ple) 均含 `train.py`、数据字段和运行说明。 | 适合核对多行为精排数据口径与建立对照；示例基于 TensorFlow 1.x/DeepRec 环境，官方 benchmark 也在 64GB Linux 环境中执行，不应作为本机 12GB 内存限制下的首选训练栈。 |

## 风险与实验闸门

1. **曝光和位置偏置**：训练日志来自旧策略；“未曝光”不是天然负例，“曝光未点”也受位置影响。第一版保留 `position`，按位置、场景和流量来源分桶汇报；后续再评估 IPS/DR 等反事实校正，不能把它当默认已解决。
2. **标签归因不一致**：必须先验证 `ordered => clicked` 是否在数据口径中成立。若不成立，ESMM 的乘积目标不适用。
3. **负迁移**：点击、成交、搜索、推荐共享 Item Tower 可能互相损害。每增加一个 loss，要求四个场景-目标离线指标都不低于已冻结基线，或明确记录可接受的业务权衡。
4. **未来信息泄漏**：用户 history、商品文本/价格、可售状态都要使用事件当时快照；按随机行切分会同时污染同一请求的正负样本和未来行为。
5. **检索/精排混淆**：带 request-item 深度交叉、价格实时性或复杂 CVR 头的模型可以用于精排，但不能直接导出独立 `v_item` 供 ANN。召回模型必须保持 item 可离线独立编码。
6. **本机资源**：遵循项目 12GB 可承受、14GB 上限约束。首轮使用向量维度 64、batch 256 或 512、截断历史 50，并先在时间连续的小样本上 smoke train；不要一次性把全量文本模型和全量商品 embedding 放入内存。

## 建议的实验阶梯

```text
E0  当前 Amazon 数据：热门/ItemCF 与采样弱负例基线
E1  当前 Amazon 数据：User-History / Item 双塔；正反馈检索 loss，并比较 `verified_purchase` 权重
E2  接入搜索日志后：搜索 Query+User-Item 双塔，搜索点击检索 loss（独立 item 向量）
E3  接入推荐曝光日志后：推荐请求塔 + 搜索请求塔共享 Item Tower 和一个 ANN 索引
E4  接入可信点击-成交漏斗后：成交样本加权或 ESMM 约束；比较点击与成交 Recall@K
E5  E3/E4 出现负迁移：MMoE/PLE 精排辅助实验，或拆 item projection/index
```

当前阶段应先完成 E0/E1；没有 `query` 不应实现 E2，缺少曝光与点击/成交链路也不应实现 E3/E4。待日志补齐后，只有 E3 同时优于或不显著差于 E1/E2 时，才应保留共享索引。若搜索 query 相关性明显下降、而推荐提升，优先采取“共享商品底层特征编码器，搜索/推荐各自 item projection 和索引”的折中，而不是继续提高多任务权重。

## 一手资料

- [Covington et al., Deep Neural Networks for YouTube Recommendations, RecSys 2016](https://arxiv.org/abs/1606.07792)
- [Ma et al., Entire Space Multi-Task Model, SIGIR 2018](https://arxiv.org/abs/1804.07931)
- [Ma et al., Modeling Task Relationships in Multi-task Learning with Multi-gate Mixture-of-Experts, KDD 2018](https://dl.acm.org/doi/10.1145/3219819.3220007)
- [Tang et al., Towards Neural Mixture Recommender for Long Range Dependent User Sequences, WWW 2019](https://arxiv.org/abs/1902.08588)
- [Gao et al., Neural Multi-Task Recommendation from Multi-Behavior Data, ICDE 2019](https://ieeexplore.ieee.org/document/8731371)
- [Tang et al., Progressive Layered Extraction, RecSys 2020](https://arxiv.org/abs/2007.07184)
- [TensorFlow Recommenders 官方多任务教程](https://www.tensorflow.org/recommenders/examples/multitask)
- [TensorFlow Recommenders 官方 retrieval 教程](https://www.tensorflow.org/recommenders/examples/basic_retrieval)
- [PyTorch TorchRec 官方仓库](https://github.com/pytorch/torchrec)
- [Alibaba DeepRec 官方 ModelZoo](https://github.com/alibaba/DeepRec/tree/main/modelzoo)
