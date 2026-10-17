# ShoppingBench 公式与公开 evaluator 核查

更新时间：2026-10-10。论文版本：[arXiv:2508.04266v4](https://arxiv.org/html/2508.04266v4)，提交于 2026-06-18。代码基准：[官方仓库提交 2f4d132500d4962d7ee3143e103b93499c82aca0](https://github.com/yjwjy/ShoppingBench/tree/2f4d132500d4962d7ee3143e103b93499c82aca0)。本文区分论文定义、当前公开代码和 RS_agent 迁移建议；没有运行完整购物 Agent、下载 embedding 模型或加载商品检索索引。

## 1. 原论文的评分单位

ShoppingBench 使用商品构造用户任务，并在终态比较预测商品和目标商品。商品相关性公式为：

\[
r_{pro}(p,t)=\frac{\mathbf1[sim(title_p,title_t)\ge0.5]+\mathbf1[min\le price_p\le max]+|F_t\cap F_p|}{2+|F_t|}.
\]

因此，`sim` 比较的是**预测商品标题与目标商品标题**，并非用户 query 与商品标题。`[min,max]` 是该目标的价格要求；`F_t` 为目标特征，`F_p` 为预测商品特征。命中全部条件才达到 1。论文正文没有说明 embedding 名称；算法细节必须另看代码。[论文 Evaluation，式 (1)](https://arxiv.org/html/2508.04266v4)

知识条件检查知识属性；店铺条件检查件数和同店；预算条件检查总价。CAR 先平均一个任务内商品相关性，再平均任务；ASR 要求相关性满分，且该意图的额外条件通过。[论文 Evaluation，式 (2)–(10)](https://arxiv.org/html/2508.04266v4)

\[
CAR=\frac1N\sum_{i=1}^N\frac1{n_i}\sum_{j=1}^{n_i}r_{pro}(p_{ij},t_{ij}).
\]

ASR 是任务完全成功比例；CAR 是部分命中的诊断分。它们没有表示用户满意度、排名位置折扣或长期购买效用。

## 2. 标题算法和价格规则的实际实现

普通商品路径使用 `SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")`，编码 `[product["title"], reward_title]` 并取 similarity 矩阵的 `[0][1]`，阈值 0.5。Qwen 官方 SentenceTransformer 配置明确 `similarity_fn_name="cosine"`、`default_prompt_name=null`，所以这里是商品标题之间的余弦相似度，没有额外 query prompt。[官方 orm.py](https://github.com/yjwjy/ShoppingBench/blob/2f4d132500d4962d7ee3143e103b93499c82aca0/src/agent/rewards/orm.py#L5-L35)；[Qwen 模型配置](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B/raw/main/config_sentence_transformers.json)

价格上下限来自 task `reward["price"]`，不是根据推荐商品临时推算：`less than` 用 `p<=upper`；`greater than` 用 `p>=lower`；`between` 用闭区间。虽然 mode 名字看起来是严格不等式，代码实际包含端点。没有 price 条件就不计价格项。代码会逐项计 reward 中声明的条件，而非无条件固定分母 `2+|Ft|`。[orm.py 价格与计数](https://github.com/yjwjy/ShoppingBench/blob/2f4d132500d4962d7ee3143e103b93499c82aca0/src/agent/rewards/orm.py#L14-L58)

公开数据也证明价格项不是普遍存在。对该提交的 JSONL 做标准库统计：Products Finder 250 个任务中 67 个 reward 没有 price、11 个只有 ID/title；shop 736 个子商品中 194 个没 price；voucher 714 个子商品均没有逐商品 price 条件，另由 voucher 预算验收。[product 数据](https://github.com/yjwjy/ShoppingBench/blob/2f4d132500d4962d7ee3143e103b93499c82aca0/data/synthesize_product_test.jsonl)；[shop 数据](https://github.com/yjwjy/ShoppingBench/blob/2f4d132500d4962d7ee3143e103b93499c82aca0/data/synthesize_shop_test.jsonl)；[voucher 数据](https://github.com/yjwjy/ShoppingBench/blob/2f4d132500d4962d7ee3143e103b93499c82aca0/data/synthesize_voucher_test.jsonl)

## 3. 特征集合到底是什么

公开实现将 service 单独计数，将 SKU 与 attributes 展平成 `(字段名,字段值)` 元组。商品每个 SKU option 单独形成一个集合；attributes 形成商品级集合。检查某个 SKU 和商品属性能满足多少 reward 项，取最佳 SKU 的命中数。属性采用精确元组匹配，没有同义词、大小写或单位归一。reward 逐项计数，所以更接近“条件命中比例”，不是完全等同于论文写的去重集合交集。[orm.py SKU/attributes](https://github.com/yjwjy/ShoppingBench/blob/2f4d132500d4962d7ee3143e103b93499c82aca0/src/agent/rewards/orm.py#L59-L99)

迁移时应将要求拆成可验条件，例如 `category=shoes`、`price<=300`、`color=blue`、`waterproof=true`，并明确规格、单位和同义词表。不能仅对全文关键词取交集：用户说“不要红色”包含“红色”，但目标约束应是排除红色。标题相似也不能保证关键属性一致。上述是我们的设计建议。

## 4. 论文与当前 evaluator 的差异及边界

| 项目 | 当前公开代码 | 迁移影响 |
|---|---|---|
| exact ID | `product_id==reward.product_id` 直接相关性 1，并不继续核对条件 | 静态目标正确时是捷径；数据更新、目标标注错误时不能保障预算等条件；我们应将 ID 有效和约束满足分开 |
| 缺失条件 | reward 未声明的条件不进分母；缺 SKU/属性通常使相应要求不命中；商品必需键缺失可能抛异常；空条件且 ID 不同会除零 | 需要 task schema 校验、未知属性状态和明确分母 |
| knowledge | 标题匹配阈值实际 0.8；知识属性在 title 或 description 里大小写不敏感 substring；exact ID 返回两个 1；相关性均值为两项平均 | 与论文统一相关性公式/标题知识检查不同；substring 不能证明知识正确，description 中否定或营销文字也可能命中 |
| 单商品任务 | 只看最后一次 `recommend_product` 的第一个逗号分隔 ID | 其他推荐不验；不是多商品列表评测 |
| 多商品任务 | 预测列表按位置对应目标 reward；分母用目标件数；超出目标数量的 ID 不处理；没有唯一 ID 检查 | 可能忽略额外违规商品、重复填充；合理的重新排序可能被位置对齐错误处罚 |
| 缺失运行 | 按存在的 rollout query 遍历，未运行的任务不进分母；重复 query 会覆盖；最多读前 501 条记录 | 评测应从固定 task manifest 出发，缺失/失败运行仍计入；同任务多次 trial 应有独立 ID |
| format/terminate | 有 format 和 length 分数，但 ASR 判断不包含它们 | 即使报告格式/终止异常，相关性仍可通过；产品验收应另定必要协议 |

来源：[orm.py](https://github.com/yjwjy/ShoppingBench/blob/2f4d132500d4962d7ee3143e103b93499c82aca0/src/agent/rewards/orm.py)；[run_evaluate.py](https://github.com/yjwjy/ShoppingBench/blob/2f4d132500d4962d7ee3143e103b93499c82aca0/src/agent/run_evaluate.py)。这些是当前发布实现的可观察行为，不代表论文报告数字已经被这些问题实际影响。

预算路径只对按目标数量取得的商品求和；若原价已满足预算直接通过，否则检查平台/同店券、满减门槛和减免上限。多件同店计数用“取到目标数量个商品”，而不是检验整份输出的严格长度与唯一性。[run_evaluate.py 多商品与券预算](https://github.com/yjwjy/ShoppingBench/blob/2f4d132500d4962d7ee3143e103b93499c82aca0/src/agent/run_evaluate.py#L93-L160)

### 轻量执行核查

使用 Python AST 只提取官方函数，通过固定 similarity=0.6 与内存商品 doc 桩调用；没有导入 embedding/index。该核查验证控制流，不能验证真实 embedding 分类准确率。

| 输入情境 | 官方函数结果 |
|---|---|
| ID 正好是目标，但 price=100 超过 reward 上限 10 | rule=1，证明 exact-ID 绕过其他条件 |
| reward 只有 title，similarity=0.6 | rule=1，证明分母不是总有标题+价格两项 |
| price=100，reward 的 `less than` 上限100 | rule=1，证明边界为 <= |
| ID 不同、reward 无任何条件 | `ZeroDivisionError` |
| 目标两个商品，输出正常两个 ID 后附不存在 ID | rule=1、shop=1，证明额外尾部不处理 |
| 输出相同 ID 两次且其满足两个相似 title 条件 | rule=1、shop=1、gt=0.5，证明没有唯一性要求 |
| 目标两个商品，仅输出一个 | rule=0.5、shop=0，证明缺失位置保留零贡献 |

上述为本地执行结果，原逻辑来源仍是固定提交的官方函数。当前 evaluator 同 ID 快捷路径还会让 field 统计空计数，`set_eval_score` 将没有条件的字段统计为 1；因此打印 price/service match=1 不等于这些条件确实被检查过。[run_evaluate.py field 统计](https://github.com/yjwjy/ShoppingBench/blob/2f4d132500d4962d7ee3143e103b93499c82aca0/src/agent/run_evaluate.py#L70-L78)

## 5. RS_agent 拟议公式的独立审查

以下是迁移建议，**不是 ShoppingBench 原公式**。适用于固定商品集合下推荐同一需求的有序列表；套餐、跨店券和多种商品采购需要额外集合约束。

设任务 q 的冻结候选全集为 `Cq`，硬要求集合 `Hq`，已定义软偏好集合 `Sq`。每项硬判定有 `true/false/unknown` 三态：

\[
h_j(p,q)=\mathbf1[\text{条件 }j\text{ 有证据确认满足}],\qquad
H(p,q)=\mathbf1[p\in C_q]\prod_{j\in H_q}h_j(p,q).
\]

未知硬属性贡献 0，但报告需区分“明确违反”和“无法核实”。如果评测作者自己也没有足够信息判断，且任务要求必须判真，则先修任务数据；不能把坏标注隐身为模型失败。缺属性与已证实不满足是不同原因。

软效用可使用静态权重和可说明的分档函数：

\[
U(p,q)=\frac{\sum_{k\in S_q}w_k s_k(p,q)}{\sum_{k\in S_q}w_k},\quad
w_k\ge0,\;s_k\in[0,1],\qquad g(p,q)=H(p,q)U(p,q).
\]

未知软属性不能从分母删掉重新归一，否则缺信息的商品反而可能得满分。可报告一个保守分与未知权重比例；需要时给上界区间做诊断。无软偏好的任务建议令 `U=1`，此时仅量度合规与覆盖，不宣称能区分细微质量。权重、分档及软条件为空的约定必须提前固定。

硬 gate 避免“超预算但标题接近”赚取商品质量分；但仅把一件坏商品 gain 置零，列表仍可能靠其他好商品得到高分。用于接受候选 Skill 时，应另设“明确硬违规数=0、不可核实的关键要求已合理处理”等门槛，不让加权均分掩盖违规。

### 固定 K 的列表质量

任务自身定义 `Kq`；需要 1 件就用 K=1，不能统一要求 5 件。令位置折扣 `d_r=1/log2(r+1)`，采用线性 gain：

\[
DCG@K_q=\sum_{r=1}^{K_q}d_r\tilde g(p_r,q),\qquad
IDCG@K_q=\max_{\pi\in\mathcal L(C_q)}\sum_{r=1}^{K_q}d_r g(\pi_r,q),\qquad
Q@K_q=DCG@K_q/IDCG@K_q.
\]

其中 `L(Cq)` 是允许的不同商品列表集合；`g̃` 对缺失位置、不存在 ID、重复 ID 的再次出现取 0，保留原位置，不能删去错误后把后面的好商品提前。若各商品独立且只有不重复约束，IDCG 就是冻结候选集合按同一 g 排序的前 K 项；可行商品少于 K 时理想列表也零填充。NDCG 的定义确实是按排名折扣的收益除以理想收益，但这里具体 gain 和 gate 是项目自定义。[scikit-learn NDCG 官方定义](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.ndcg_score.html)

必须补齐这些约定：

- **固定参照集合。** 不可用“模型这次找出的候选”计算自己的 IDCG，否则漏掉好商品也能满分。为单独评价 Skill，可冻结工具候选；端到端检索能力需用完整 catalog 或固定标注池。
- **超 K 输出。** 排名只计算前 K，但整份明确推荐输出都应检查硬约束、重复和数量。否则第 K+1 项藏违规也不会被发现。
- **IDCG=0。** 没有可行商品和所有效用为 0 不是同一情况；此时 Q 无定义，任务转到无解说明/合理澄清的行为判定，不可默认满分。
- **跨商品约束。** 配套品类覆盖、同店券、预算总额和多样性使 gain 非独立，应在合法组合中求最大理想收益；不能直接取单商品 top K。
- **多需求采购。** 若目标是一鞋一包、顺序不重要，应做需求槽位到预测商品的一对一匹配，防同一商品重复覆盖；若目标是同一需求的排序推荐，才用上面的 Q。
- **未知属性。** unknown 不自动视为满足，但如任务允许“候选待确认”，应另外评价证据说明与后续核验；避免把诚实说明一律当成严重违规。

### 一个可手算的小例子

K=3，固定 catalog 的理想 gain 为 `[1,0.8,0.6]`。若 Agent 只推荐第一件，则 DCG=1、IDCG≈1.805、Q≈0.554；“只给一件最好的”不会因为按实际返回数量平均而得 1。输出 `[A,A,C]` 时第二次 A 在原位置 gain=0；未知价格的商品不通过预算硬 gate。该例仅解释公式行为，没有建立真人满意度效度。

## 6. 标题相似度的角色

建议标题 cosine 仅作为候选诊断、标题映射或任务数据复核信号，不进关键硬验收。用户 query 中包含否定、条件及软偏好，query-title cosine 不能解析其逻辑；即便商品标题与目标标题很相似，SKU、预算和排除条件仍可能不同。ShoppingBench 的思路是把相关性拆成可验条件，我们借这个结构；当前 evaluator 的具体阈值、exact-ID 捷径和位置对齐不宜照搬。

建议用于 Skill 选择的结果保留两部分：任务级“所有必要条件通过”的成功率，以及列表 Q、分项满足率、unknown/违规计数、成本。固定任务 manifest 中所有 case 均进入分母；旧版和候选在相同 catalog、工具响应、K、权重和评分版本下配对运行。上述都是待实现的评测设计，而非已验证的项目能力。

