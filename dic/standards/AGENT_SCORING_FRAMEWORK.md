# 推荐 Agent 评分体系：SFT、GRPO 与线上满意度

本文档记录推荐 Agent 后续数据生成、模型优化和真实上线评估需要复用的三套评分口径。

核心区分：

- **SFT 评分**：评估“这条样本值不值得模型学习”。
- **GRPO 评分**：评估“这个模型输出 / checkpoint 是否比 baseline 更好”。
- **线上推荐满意度评分**：评估“真实用户是否对推荐体验满意”。

三者相关，但不能混成一个总分。SFT 是数据质检，GRPO 是模型质检，线上满意度是真实用户体验质检。

---

## 1. 总体原则

推荐 Agent 的评分体系采用三层结构：

1. **硬门禁 Hard Gate**
   - 一旦触发严重错误，直接 reject 或标记为 high-risk，不因其他维度高分而放行。
2. **分项评分 Rubric Score**
   - 每个维度 0-5 分，再按权重换算到 100 分。
3. **对比偏好 Pairwise Preference**
   - 主要用于 GRPO 和 checkpoint 晋升，比较当前模型与 baseline / 上一 checkpoint 的胜负。

评分结果应结构化保存，支持后续筛选、统计、回放、回流训练和 bad case 分析。

---

## 2. SFT 数据评分

### 2.1 评价目标

SFT 评分回答的问题是：

> 这条样本是不是一个正确、干净、可学习、可复用的示范？

它关注的是**样本质量**，而不是模型当前能力。

### 2.2 硬门禁

以下问题应直接判为 hard fail：

| 硬失败类型 | 说明 |
|---|---|
| 候选池越界 | assistant 推荐了输入候选池不存在的商品 |
| 商品属性编造 | 编造价格、销量、材质、评价、库存、品牌等证据中没有的信息 |
| 标签/Oracle 泄漏 | 出现 ground truth、label、oracle、正样本、点击标签等训练/评估信息 |
| 格式错误 | messages 缺字段、assistant 为空、JSON planner 无法解析 |
| 用户意图明显错误 | 推荐方向与用户需求相反 |
| 内部信息泄露 | 暴露召回分数、DeepFM 分数、内部工具链、评估标签等 |
| 安全/合规问题 | 隐私泄露、歧视、不当引导等 |

触发 hard fail 时：

```text
SFT_score = min(SFT_score, 59)
decision = reject
```

### 2.3 分项维度与权重

| 维度 | 权重 | 衡量内容 |
|---|---:|---|
| 用户意图理解 | 15 | 是否识别用户需求、场景、预算、偏好、禁忌 |
| 推荐相关性 | 20 | 推荐商品是否匹配用户需求和上下文 |
| 候选池一致性 | 15 | 是否只从候选池推荐，是否尊重召回/排序边界 |
| RAG 证据一致性 | 15 | 解释是否来自商品证据，不编造 |
| 多轮对话质量 | 10 | 是否会澄清、承接反馈、避免机械回答 |
| 解释质量 | 10 | 理由是否具体、自然、不过度营销 |
| 输出格式/协议 | 10 | 是否符合 messages、JSON planner、tool_calls 等协议 |
| 训练价值 | 5 | 是否有代表性，是否能教会模型有用行为 |

总分计算：

```text
SFT_score = Σ(维度分 / 5 * 权重)
```

### 2.4 评分档位

| 总分 | 决策 | 用途 |
|---:|---|---|
| ≥ 85 | accept | 高质量 SFT 数据 |
| 75-84 | accept_light | 普通 SFT 数据，可降权或分层使用 |
| 60-74 | rewrite | 进入重写池，不直接训练 |
| < 60 | reject | 丢弃 |
| hard fail | reject / bad_case | 不作为正样本训练，可用于回归测试 |

### 2.5 推荐保存字段

```json
{
  "sample_id": "sft_000001",
  "task_type": "multi_turn_recommendation",
  "scenario": "budget_constraint",
  "hard_fail": false,
  "hard_fail_reasons": [],
  "scores": {
    "intent_understanding": 5,
    "recommendation_relevance": 4,
    "candidate_pool_consistency": 5,
    "rag_grounding": 4,
    "dialogue_quality": 4,
    "explanation_quality": 4,
    "format_protocol": 5,
    "training_value": 4
  },
  "total_score": 88,
  "decision": "accept",
  "rewrite_suggestion": null
}
```

---

## 3. GRPO 模型评分

### 3.1 评价目标

GRPO 评分回答的问题是：

> 当前模型输出或 checkpoint 是否真的比 baseline / 上一版更好？

它关注的是**模型行为质量**，不是单条训练样本是否干净。

### 3.2 评分组成

GRPO 评价应同时包含：

1. **Absolute Score**：单条输出 0-100 分。
2. **Pairwise Preference**：当前 checkpoint vs baseline / 上一 checkpoint 的 win/tie/lose。
3. **Hard Failure Rate**：候选池越界、幻觉、约束违反、解析失败等严重问题占比。

### 3.3 分项维度与权重

| 维度 | 权重 | 衡量内容 |
|---|---:|---|
| 任务完成度 | 20 | 是否真正解决用户当前推荐请求 |
| 推荐质量 | 20 | 推荐是否相关，排序是否合理，是否覆盖关键偏好 |
| 反馈适应能力 | 15 | 用户补充、否定、纠正后是否能调整 |
| 证据 grounding | 15 | 是否基于候选商品和 RAG 证据解释 |
| 约束遵守 | 10 | 预算、品牌、品类、场景、禁忌是否遵守 |
| 对话自然度 | 10 | 是否简洁、自然、不机械、不啰嗦 |
| 鲁棒性 | 5 | 同类输入、多次采样下是否稳定 |
| 安全与边界 | 5 | 不泄露内部标签，不编造，不越权 |

总分计算：

```text
GRPO_absolute_score = Σ(维度分 / 5 * 权重)
```

### 3.4 Pairwise Preference

GRPO 必须保留相对比较结果，建议比较对象包括：

- 当前 checkpoint vs SFT baseline
- 当前 checkpoint vs 上一 checkpoint
- 当前 checkpoint vs deterministic/rule baseline

保存格式示例：

```json
{
  "eval_id": "grpo_eval_000001",
  "prompt_id": "eval_prompt_000123",
  "model_a": "sft_baseline",
  "model_b": "grpo_checkpoint_003",
  "winner": "model_b",
  "preference": "win",
  "confidence": 0.82,
  "reasons": [
    "model_b 更好地处理了用户新增预算约束",
    "model_b 的解释更贴合候选商品证据",
    "model_a 回答更泛化"
  ],
  "failure_flags": []
}
```

### 3.5 Checkpoint 晋升指标

每个 GRPO checkpoint 至少统计：

| 指标 | 含义 |
|---|---|
| absolute_mean_score | 平均绝对分 |
| pairwise_win_rate_vs_sft | 相比 SFT baseline 胜率 |
| pairwise_win_rate_vs_prev | 相比上一 checkpoint 胜率 |
| hard_fail_rate | 严重错误率 |
| candidate_violation_rate | 候选池越界率 |
| hallucination_rate | 商品属性 / RAG 幻觉率 |
| constraint_violation_rate | 用户硬约束违反率 |
| multi_turn_success_rate | 多轮反馈成功率 |
| json_parse_success_rate | JSON planner / tool_calls 解析成功率 |
| average_response_length | 平均回答长度，防止 reward hacking 变啰嗦 |

建议晋升门槛：

```text
pairwise_win_rate_vs_sft >= 55%
hard_fail_rate <= 3%
candidate_violation_rate <= 1%
hallucination_rate <= 3%
constraint_violation_rate <= 3%
multi_turn_success_rate 不低于 baseline
average_response_length 不异常上涨
```

如果平均分提高但 hard fail rate 同时提高，不应晋升。

---

## 4. SFT 与 GRPO 的区别

| 对比项 | SFT 评分 | GRPO 评分 |
|---|---|---|
| 评价对象 | 数据样本 | 模型输出 / checkpoint |
| 核心问题 | 值不值得学？ | 是否真的变好？ |
| 主要方式 | absolute rubric | absolute + pairwise |
| 重点 | 干净、可学、无污染 | 策略改进、胜率、稳定性 |
| hard fail 处理 | 直接 reject | 统计 failure rate，决定是否晋升 |
| 输出结果 | accept / rewrite / reject | win / tie / lose + checkpoint report |
| 主要风险 | 低质量样本污染模型 | reward hacking、平均分虚高 |
| 代表指标 | accept rate、rewrite rate、维度均分 | win rate、hard fail rate、场景分层表现 |

---

## 5. 线上推荐满意度评分

### 5.1 评价目标

线上满意度评分回答的问题是：

> 真实用户是否觉得这次推荐有用，并产生了正向行为或明确满意反馈？

线上满意度不能只靠 LLM judge，需要结合真实用户信号。

### 5.2 三类信号

#### 5.2.1 显式反馈

| 信号 | 说明 |
|---|---|
| 点赞 / 点踩 | 用户明确喜欢或不喜欢 |
| 1-5 星评分 | 会话后评分 |
| 有帮助 / 没帮助 | 推荐解释是否有用 |
| 用户文字反馈 | “这个不错”“不适合”“太贵了”等 |

示例归一化：

```text
点赞 = 1.0
中立 = 0.5
点踩 = 0.0
5星 = 1.0
4星 = 0.8
3星 = 0.5
2星 = 0.2
1星 = 0.0
```

#### 5.2.2 隐式行为

| 行为 | 解释 |
|---|---|
| 点击推荐商品 | 基本兴趣 |
| 查看详情页 | 更强兴趣 |
| 停留时间长 | 商品有吸引力 |
| 收藏 / 加购 | 强正反馈 |
| 购买 / 转化 | 最强正反馈 |
| 分享 | 高价值正反馈 |
| 立即退出 | 负反馈 |
| 反复改问 | 可能不满意，也可能是深度探索，需要结合结果判断 |
| 明确说“不喜欢/不是这个” | 强负反馈 |
| 跳过所有推荐 | 负反馈 |

行为得分示例：

```text
behavior_score =
0.15 * click
+ 0.20 * detail_view
+ 0.25 * favorite_or_cart
+ 0.35 * purchase
+ 0.05 * dwell_time_quality
- negative_penalty
```

#### 5.2.3 对话成功信号

| 指标 | 说明 |
|---|---|
| task_success | 用户问题是否被解决 |
| clarification_efficiency | 是否用少量澄清拿到关键偏好 |
| feedback_recovery | 用户否定后是否成功调整 |
| repetition_rate | 是否重复推荐无效商品 |
| turns_to_success | 几轮内达成满意推荐 |
| abandonment_rate | 用户是否中途离开 |
| complaint_rate | 用户是否抱怨“不准”“太贵”“不相关” |

对话得分示例：

```text
dialogue_score =
0.35 * task_success
+ 0.25 * feedback_recovery
+ 0.20 * clarification_efficiency
+ 0.20 * naturalness
- repetition_penalty
- abandonment_penalty
```

### 5.3 Session-level SatisfactionScore

有显式反馈时：

```text
SatisfactionScore =
0.35 * explicit_score
+ 0.30 * behavior_score
+ 0.20 * dialogue_score
+ 0.10 * constraint_success_score
+ 0.05 * trust_safety_score
```

无显式反馈时：

```text
SatisfactionScore =
0.45 * behavior_score
+ 0.30 * dialogue_score
+ 0.15 * constraint_success_score
+ 0.10 * trust_safety_score
```

### 5.4 约束与信任安全

线上满意度不能只看点击率。以下问题应强惩罚：

- 用户说预算 200 内，却推荐 399 元商品。
- 用户明确不喜欢某类商品，仍反复推荐。
- 编造商品属性、销量、评价、库存。
- 暴露内部召回、排序、标签、oracle 信息。
- 推荐候选池外商品。

即使用户有点击行为，硬约束违反也应降低满意度或进入 bad case。

### 5.5 保存粒度

线上日志建议至少保存三层。

#### item-level

```json
{
  "item_id": "i001",
  "clicked": true,
  "detail_view": true,
  "dwell_seconds": 32,
  "favorite": false,
  "cart": false,
  "purchase": false,
  "explicit_feedback": "like"
}
```

#### turn-level

```json
{
  "turn_id": "t003",
  "intent": "recommend_request",
  "constraint_success": true,
  "grounding_violation": false,
  "user_reaction": "asked_detail",
  "turn_satisfaction_score": 0.78
}
```

#### session-level

```json
{
  "session_id": "s001",
  "task_success": true,
  "turns_to_success": 3,
  "explicit_score": 1.0,
  "behavior_score": 0.72,
  "dialogue_score": 0.81,
  "constraint_success_score": 1.0,
  "trust_safety_score": 1.0,
  "satisfaction_score": 0.84
}
```

---

## 6. 回流闭环

推荐 Agent 上线后，评分体系应形成闭环：

```text
线上会话日志
  ↓
行为信号打分
  ↓
用户显式反馈收集
  ↓
规则检测 hard fail
  ↓
LLM judge 抽样复评
  ↓
形成 satisfaction report
  ↓
沉淀 high-quality / bad-case session
  ↓
回流 SFT / GRPO 数据池
```

回流建议：

| 数据来源 | 后续用途 |
|---|---|
| 高满意会话 | SFT 候选样本 |
| 明确不满意会话 | bad case / hard negative |
| 当前模型明显优于旧模型的会话 | preference 数据 |
| 幻觉、越界、约束失败会话 | 回归测试与 hard fail 校准 |
| 多轮成功恢复案例 | 反馈适应能力样本 |

---

## 7. 面试可讲点

这套评分体系可以表述为：

> 我没有把 Agent 训练简单理解成“生成更多样本”，而是把数据生成、模型优化和线上反馈拆成三套评价口径。SFT 阶段重点做数据质检，防止模型学习候选池越界、RAG 幻觉和标签泄漏；GRPO 阶段重点做 checkpoint 质检，用 pairwise win rate 和 hard fail rate 防止 reward hacking；真实上线后再用显式反馈、隐式行为、对话成功和信任安全组成 session-level 满意度分数，并把高满意和 bad case 会话回流到后续 SFT/GRPO 数据池。这样可以把推荐 Agent 从离线训练、偏好优化到真实用户反馈连成可验证闭环。
