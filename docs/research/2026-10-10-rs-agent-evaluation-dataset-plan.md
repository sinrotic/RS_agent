# RS_agent 自进化评测集：资料核查与起步方案

研究日期：2026-10-10。范围：公开论文、作者仓库、官方工程资料，以及当前工作区的 Agent、Skill、仿真和评测实现。本文记录研究与建议，没有实现评测器、修改 Skill 或运行模型实验。样本量、比例、任务字段和阶段安排是项目建议，不是论文证明的通用阈值。

网络专题与数据获取核查见 [一手资料研究](2026-10-10-agent-evaluation-dataset-sources.md)。

## 1. 结论与优先级

评测集给自进化提供改进方向；可信评分规则和可复现环境让改进信号成立。对 RS_agent，应先把“好推荐”拆成能验收的事实和行为，再收集任务。一个完整任务至少包含：用户输入、当时可见的上下文、固定商品与工具环境、可接受结果、验收规则及来源。

建议先做两个切片：**推荐解释不虚构事实**、**用户修改预算后保留其他有效约束**。这两类可以借 Catalog Item、RAG Evidence 和显式用户反馈形成较客观的判定。澄清策略随后补充，因为当前 Skill 对何时追问、何时直接给选项存在不一致。

开始时，30–50 条经人工审核的任务可以发现明显改善和回归，但不够证明微小增益。Anthropic 的实践建议也是从少量真实失败和已有手工检查开始，并同时覆盖应触发与不应触发的行为。其建议支持小规模起步，不意味着“凑够某个数量即可安全全自动优化”。[Anthropic 官方工程说明](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

## 2. 查到哪些可以借鉴的工作

| 一手来源 | 核心方法 | 对项目的借鉴与限制 |
|---|---|---|
| [τ-bench 论文](https://arxiv.org/abs/2406.12045)、[官方代码](https://github.com/sierra-research/tau-bench) | 初始业务状态、用户目标、工具和政策；模拟用户交互；按终态验收并重复试验 | 借任务结构和环境重置。售后任务的终态正确不等于推荐令人满意 |
| [ShoppingBench](https://arxiv.org/html/2508.04266v1)、[作者仓库](https://github.com/yjwjy/ShoppingBench) | 从真实商品抽样、提取属性、生成用户需求，再按商品属性及业务约束评分 | 很适合借“商品事实 → 结构化目标 → 用户表达”的构造流程；价格和特征可验，标题相似度不能直接成为我们的推荐质量标准 |
| [CheckList](https://aclanthology.org/2020.acl-main.442/)、[作者代码](https://github.com/marcotcr/checklist) | 按能力和测试类型构造最低功能、不变性和方向性测试 | 为同一需求设计改写、否定、预算变更、画像冲突等任务，检查该不变和该改变的行为 |
| [Google ConvApparel](https://research.google/blog/convapparel-measuring-and-bridging-the-realism-gap-in-user-simulators/)、[官方数据](https://huggingface.co/datasets/google/ConvApparel) | 真实人机服装购物对话，逐轮体验标注，检验模拟用户面对不同推荐行为的反应 | 借采集和标注方法；英文服装数据需要重新适配中文及本地目录，原标签不能贴到我们新生成的回答上 |
| [PEPPER，EMNLP 2025](https://aclanthology.org/2025.findings-emnlp.1067/) | 避免预设唯一目标商品的用户模拟，评价偏好探查 | 用户发现合适商品可以有多个答案；“猜中唯一商品 ID”不应成为所有任务的唯一成功条件 |
| [用户模拟器局限研究](https://arxiv.org/abs/2403.16416) | 分析历史和用户回复的目标泄漏、模拟控制问题 | 隐藏答案不得随用户回复泄漏；模拟用户的接受不能直接替代真人满意度 |
| [MT-Bench / Chatbot Arena](https://arxiv.org/abs/2306.05685) | 分析模型裁判的位置、长度、自我偏好和推理局限 | 人工校准、隐藏版本身份、交换 A/B 顺序，并保留未知与复核结果 |
| [LangSmith 数据管理](https://docs.langchain.com/langsmith/manage-datasets) | 轨迹转数据集、数据版本、划分和固定版本评测 | 这些实践可在本地 JSONL/YAML 上实现；不需要先接某个平台 |
| [自适应 holdout 研究](https://arxiv.org/abs/1506.02629) | 反复根据同一留出集反馈挑选候选会使留出集过拟合 | 优化用选择集之外，再留锁定测试和新的真实任务 |

另核查了新预印本 [RealWorldShop（2026-09）](https://arxiv.org/html/2609.38974v1)：它把目录快照、结构化购物 Session、用户可见/隐藏状态和多层评估结合起来，值得参考任务分解。此次未确认可下载的完整代码与数据，也未复现实验；其模拟和模型裁判结果不作为已在本项目验证的结论。

外部数据适合用来发现任务类型、观察真人语言及做额外诊断。正式的内部基准仍需使用本项目支持的工具、目录事实、画像和产品规则。公开电影、服装对话及售后数据不能直接承担中文购物 Skill 的最终验收。

## 3. 本地已经有什么，以及当前缺口

### 3.1 可复用的资产

- Java [AgentLoop](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/AgentLoop.java) 接受运行请求并产出 `tool_use`、`tool_result`、`answer_block`、`model_usage` 等事件。当前 [编排实现](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/service/impl/InMemoryAgentOrchestrationService.java) 实际调用 `agentLoop.run`；不能沿用旧结论，把它一概当作硬编码模拟。
- [平台 trace 接口](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/controller/platform/PlatformAgentTraceController.java) 与 [AgentTurnVO](../../java_agent/rs-service-agent/src/main/java/com/sinrotic/rs/agent/domain/vo/AgentTurnVO.java) 提供用户输入、回答、工具记录和推荐 ID，适合识别失败。构造完整可复现任务还需另保存运行配置、初始状态和足够的工具结果；不能假设这个 VO 包含全部事实。
- [已有 Python 仿真](../../python_agent/rs_core/offline/simulation/runner.py) 有批量场景、反馈动作和接受/停止；[用户角色](../../python_agent/rs_core/offline/simulation/presets.py) 有通勤、送礼、价格敏感三类，可借场景定义。
- [Python artifact](../../python_agent/rs_core/offline/evaluation/agent_artifact.py) 已组织轨迹、工具事件、scorecard 和训练信号，可借产物形状。
- [pool500 冻结候选评测构造](../../python_agent/rs_lab/experiments/ranking/build_pool500_frozen_candidate_eval_dataset.py) 已区分候选与评价标签、训练历史特征及时间截点。这些约束可以延用到 Agent 任务，但推荐排序标签不是对话策略的完整真值。

### 3.2 当前分数不能直接决定 Skill 晋级

核对 [agent_scorecard.py](../../python_agent/rs_core/offline/evaluation/agent_scorecard.py) 可见：

1. 没有 `offline_metrics` 时，`recommendation_effectiveness` 使用“有 final_items 的 Turn 比例”。这衡量是否返回商品，没有判断商品是否满足用户要求；还可能惩罚合理的澄清。
2. `_memory_consistency` 中 `liked` 来自当前 liked 集合，随后验证它是否是同一集合的子集；disliked 同理。两项恒为真，不能验证跨 Turn 保留。
3. `training_data_quality` 衡量样本/事件覆盖，却与业务能力一起等权平均；更多数据字段不代表更好的 Skill。
4. [run_agent_evaluation.py](../../python_agent/scripts/evaluation/run_agent_evaluation.py) 当前候选是 `baseline` 与 `enhanced_feedback_rerank`，执行的是 Python RecommendationService 仿真；这条调用链没有执行 Java 的 Skill 加载与 AgentLoop。现有结果不能直接用来比较 Java Skill 文本。
5. [规则用户策略](../../python_agent/rs_core/offline/simulation/policy.py) 的接受依据主要是类目/关键词加分和价格阈值，不能把规则满意度当作真实满意度。其“没有商品就要求具体选项”的动作也不适合所有澄清任务。

这些是静态代码核查，没有运行实验或改实现。

### 3.3 先统一含糊需求的产品规则

[unclear-need-clarification](../../java_agent/rs-service-agent/src/main/resources/agent-skills/unclear-need-clarification/SKILL.md) 的 Workflow 允许画像推荐与冷启动推荐；Stop Conditions 又要求必须发出澄清问题。[cold-user-onboarding](../../java_agent/rs-service-agent/src/main/resources/agent-skills/cold-user-onboarding/SKILL.md) 对含糊需求也同时包含提问与冷启动选项。

前面对话中“含糊需求必须同时问类别和关键约束”的例子过于刚性，当前 Skill 更倾向一个简短问题，而且部分场景允许直接探索选项。正式标签必须由产品目标决定，不能照抄任何一版 Skill 的措辞作为正确答案。

建议先标三种情境：用户明确要求先询问；用户明确要求直接给探索选项；用户没有指定交互方式。前两类通常可判断，第三类需要根据可用画像、需求可行性和交互目标允许多种有效结果，或暂列待审核。规则冲突没有解决的任务不用于自动晋级。

### 3.4 已有报告可以贡献真实失败种子

[2026-10-09 容量报告](../reports/agent-capacity-20261009/README.md) 的比较任务明确要求一般性建议、不查商品或用户历史，却在 12 个比较 Turn 中调用 RAG 委派并失败，然后继续回答。报告也明确说明候选是开发占位数据、部分依赖未运行。

可以从这些证据中构造“通用选购建议不触发无关检索”和“依赖失败后如实处理”的任务。但这些压测不是代表真实购物分布的用户研究；3895 次重复请求也不是 3895 个独立业务任务。

## 4. 如何形成第一批任务

### 4.1 四条来源并行收集

| 来源 | 收集方法 | 标签依据 |
|---|---|---|
| 真实失败和真实成功 | 从 Session/trace、用户反馈、人工调试记录抽取某个 Turn 前的可见上下文 | 当时用户要求、目录和证据、人工判定的具体原因 |
| 产品验收场景 | 从当前功能和明确规则写出任务，包括不应触发的行为 | 产品负责人认可的目标与约束 |
| 目录事实生成 | 从可信 Catalog Item 抽取可验证属性，先建立目标及可行结果，再生成自然用户表达 | 固定目录事实和可执行约束 |
| 受控变体 | 对以上种子改措辞、预算、画像、反馈和证据可用性 | 保持语义的标签或明确改变后的新标签 |

没有线上流量时，可以让团队成员真实试用并逐轮记录“有用/无用，原因是什么”，同时人工编写目录可解任务。不需要等成熟线上日志，但必须记录来源，不能把内部试用频率当成线上分布。

首批可暂定 40 个种子：10 个真实失败、10 个真实成功/日常任务、10 个产品验收、10 个目录约束任务。这个比例仅方便启动；来源不足时用明确标记的人工试用/任务替代。先审核种子，再扩增，每个种子保留 `family_id`。

### 4.2 从真实商品反向构造可验证需求

借鉴 ShoppingBench 的构造方法：固定小型真实目录，抽取可信属性，生成结构化目标，证明目标有解，再让模型把目标写成自然用户语言。ShoppingBench 自身按标题相似、价格、特征及其他购物约束评分；我们借生成流程，不直接照搬标题相似度阈值。[论文任务构造与评分](https://arxiv.org/html/2508.04266v1)

例如先固定：耳机类、价格不超过 300、明确支持无线、有目录可核实的重量属性。再生成“通勤用，300 以内，想要无线且轻一点”的说法。验收“300 以内”时使用硬上限；“轻一点”若没有定义阈值或比较对象，则是软偏好，不能偷偷设一个用户看不到的重量阈值。

用冻结的小目录计算所有满足硬约束的可接受商品，不只记录生成任务时抽到的那件。开放式软偏好由人工等级/成对比较补充；缺属性标记未知，禁止用未知事实声称满足约束。构造时再放入便宜但属性不符、属性符合但超预算等干扰商品。

需要加无解任务：无符合条件的商品时，成功可以是准确说明缺口并提出用户可选择的放宽条件。不能奖励凭空推荐，也不能把所有任务的“不给商品”都认定成功。

### 4.3 覆盖矩阵

| 能力 | 正常任务 | 对照/挑战任务 | 验收重点 |
|---|---|---|---|
| 明确需求推荐 | 用户给出足够品类、用途和约束 | 画像与当前需求冲突；无解；属性未知 | 真实商品、显式约束、当前请求优先、如实表达未知 |
| 澄清与路线选择 | 明确需要追问的输入 | 信息已足够；已知信息不得重复问；用户要求直接探索 | 有用的信息获取与合适路线，允许有效替代方案 |
| 证据解释 | 对已有商品问“为什么” | 证据缺失、冲突或与其他商品混淆 | 解释逐项有依据、没有虚构或不当扩充商品集合 |
| 反馈适应 | 只降低预算或拒绝一件商品 | 多次纠正；明确要求比较曾拒绝商品 | 修改指定约束、保留其他约束、正确理解例外 |
| 冷用户 | 缺画像但需求明确 | 画像弱且需求广；已有可靠画像 | 不虚构长期偏好，根据当前需求行动 |
| Session 状态 | 多 Turn 预算/用途逐步明确 | 代词引用、偏好更新、Session 切换与压缩 | 已知约束按其有效范围保留；标签不使用未来才披露的信息 |

Session 状态同时受运行时影响，不能把所有状态失败归咎于 Skill。新增 [A2UI Skill](../../java_agent/rs-service-agent/src/main/resources/agent-skills/a2ui-interface/SKILL.md) 可另设界面任务：商品 ID 来源、组件树和协议、用户确认查询后能继续任务；应区分协议代码测试与真实模型生成质量。

### 4.4 扩增应验证方向

CheckList 的最低功能、不变性和方向性测试可转化成这些检查：[论文](https://aclanthology.org/2020.acl-main.442/)

- 不变性：改同义词、口语和轻微错字，核心约束及有效行为基本不变。
- 方向性：预算由 500 降到 300 后，新推荐必须满足新上限；没有改动的用途/品类继续有效。
- 反事实：同一句请求给有画像/无画像，或有证据/无证据；行为按可用信息改变。
- 负例：信息充分时继续冗长追问；用户只问通用建议时查询商品；没有证据却确定承诺。

改写数量不能替代独立种子数量。扩增后若目标和自然语言不一致、约束无法核实或两位审核者无法给出一致标准，先退回待审核。

## 5. 任务结构：先评一个 Turn，再评完整 Session

第一阶段截取固定上下文，让旧版和候选回答同一 Turn；这比直接引入自由用户模拟器更容易定位变化。随后做可分支 Session：用户按实际提问回答、按实际商品反馈。旧日志后续原句在候选行为改变后可能不再合理，不能机械续接。

以下仅是建议的数据记录形状，不是已实现 schema，也不是来自真实 Catalog Item 的样本：

```yaml
id: budget_update_001
family_id: dogfood_session_017
source: human_dogfood
capabilities: [feedback_adaptation, constraint_retention]
initial_state:
  session_prefix: fixture_session_017_v1
  known_constraints:
    category: headphones
    wireless: true
    budget_max: 500
  rejected_item_ids: [item_previous_1]
input:
  user_message: "还是太贵了，最多 300，其他要求不变"
environment:
  catalog_snapshot: catalog_v1
  tool_environment: recommendation_fixture_v1
oracle:
  expected_constraints:
    category: headphones
    wireless: true
    budget_max: 300
  acceptable_outcomes:
    - recommend_verified_feasible_items
    - explain_no_match_if_feasible_set_empty
  hard_checks:
    - only_returned_candidate_ids
    - obey_updated_budget
    - retain_wireless_requirement
    - do_not_repeat_rejected_item_unless_explicit_comparison
  semantic_checks:
    - acknowledge_budget_change_without_redundant_questions
    - support_product_claims_with_visible_evidence
review:
  status: reviewed
  policy_version: shopping_policy_v1
```

`oracle`、可行结果集合和未来用户计划只供评分器/模拟器使用，不能混进被测模型的上下文。模型可以通过实际工具取得商品事实；隐藏的是答案及未来偏好，不是故意剥夺正常业务信息。

## 6. 环境怎样才可复现且能评价 Skill

Skill 文本比较需要真实目标模型执行当前 Java 运行路径，冻结模型配置、其他 Skill、系统提示、工具 schema 和运行时配置。每次运行清空或恢复 Session、Session Preference、Profile Preference 及其他评测状态。

第一阶段把目录、候选和 RAG 数据固化为小型工具环境，保留接口形状；工具根据合法参数返回对应结果。不能把旧轨迹中第 N 次调用的结果机械喂给候选，因为候选可能使用不同查询、不同商品 ID 或不同有效路径。可以让环境确定化，不能把被测模型输出写死。

分开两种实验：完整运行时测试 Skill 是否正确选择/加载；固定注入候选 Skill 测正文是否改善行为。允许合法组合 Skill，不把唯一 Skill 名或全套工具顺序作为所有任务的正确答案。不可替代的协议动作和“候选存在后才能取该候选证据”等依赖可单独验收。

现场集成测试与固定环境评测分开报告：推荐服务不可用、解析失败、模型额度不足和错误评分都可能造成失败。保留 `agent_behavior_error`、`runtime_error`、`environment_error`、`invalid_task`、`judge_uncertain` 等诊断原因；不删除困难失败来抬高通过率。

这一方案是为隔离 Skill 效用的建议，不意味着小目录分数能代表全量召回、排序或真实用户价值。成熟后需要补完整服务链路和真人验证。

## 7. 怎样判分，怎样验证评分器

### 7.1 三类结果分别保存

1. **任务结果与硬约束：**是否完成该任务目标；是否存在商品、超预算、违反已知要求、无依据承诺。程序能查的优先程序查。
2. **语义质量：**问题是否有用、解释是否对应证据、反馈是否被理解。按具体维度判定，不要求复述标准句；可用已校准的模型与人工。
3. **成本与诊断：**Turn 数、模型调用、工具失败、token、耗时。效率用于成功任务之间的比较；不能让快速放弃得到高分。

一个任务的通过条件可定义为：`达到可接受结果 AND 本任务全部必需检查通过`。同时保留每项细分结果解释失败。缺真值的维度标未知/不适用，不能无依据记为成功；最终报告评测覆盖率及未判定数量。

用户只要一般建议的任务不要求返回商品；直接推荐任务不能只靠“不超预算”空列表而通过；无解任务也不能因没有商品而判错。硬约束与软偏好按用户原话及人审规则划分，评分器不能增加隐含要求。

### 7.2 独立构造评分器校准集

先做 20–30 个明确好/坏输出对作为试验起点，再逐渐扩大：正确输出；预算超标；不存在商品；丢失未改变的用途；引用错误商品证据；无证据承诺；冗长但没有帮助的回答；合理无解回应。

验证评分器能拒绝明显错误，也不会误杀合法替代方案。需要语义裁判时，让了解产品的人给参照标签，检查假通过和假失败；有条件时两人独立标注并处理分歧。成对判断隐藏版本、交换 A/B 顺序，不一致时复核。校准集和评分规则独立于 Skill 优化器；优化器不能为了通过改评分标准。模型裁判偏差已有实证，不因模型更大就自动可信。[MT-Bench](https://arxiv.org/abs/2306.05685)

### 7.3 用户模拟器是下一阶段

多轮初期可以由规则状态控制“问到预算就给预算；忽略预算就指出；只否定价格时其他约束保持”；LLM 只将合法动作写成自然语句。随后用真实对话检验它的偏好一致性、隐藏信息披露、拒绝行为与终止条件。

PEPPER 提醒预置目标商品会造成猜答案式优化；ConvApparel 提供真人逐轮体验及模拟器验证方法；推荐模拟器研究发现泄漏和控制问题。它们支持保留多个可接受结果，并用真人行为验证模拟器，而不是用另一个 LLM 的“我满意了”作为全部晋级依据。[PEPPER](https://aclanthology.org/2025.findings-emnlp.1067/)、[ConvApparel](https://arxiv.org/abs/2602.16938)、[模拟器局限研究](https://arxiv.org/abs/2403.16416)

## 8. 数据划分、自动迭代与维护

先按种子来源/原 Session/问题族分组划分，再合成改写；同源样本不跨优化集、选择集和锁定测试。足够数据后增加新品类、新表达和较晚时间段任务，观察外推能力。

优化集可把失败轨迹给优化器；选择集用于筛候选；锁定测试在选定版本的阶段性验收时使用。查看锁定测试失败后再修改，该任务即进入已知回归范围，下次未知验收应补新的任务。反复自适应查询留出集会过拟合，单纯称它“验证集”并不能解决。[holdout reuse 研究](https://arxiv.org/abs/1506.02629)

每轮固定任务版本、评分版本和环境。新增任务先审核，形成下一版本；不能同一轮修改 Skill 又修改标签而宣称涨分。版本管理实践可参考 [LangSmith](https://docs.langchain.com/langsmith/manage-datasets)，本地文件与 manifest 已足以起步。

旧版/候选做配对运行，初期对重要任务重复 3 次检查波动。报告修复、退化、不变和不稳定任务、各能力通过率及成本；扩增和重复运行都不算新增独立种子。统计分析应按 Session/问题族聚类，小样本领先一两题只作候选改进证据，不作为已证明的线上增益。

自动接受门槛应提前确定：硬规则不允许退化；目标能力改善有足够证据；其他能力没有明显回归；未知或裁判分歧先人审。尚未建立稳定真值时只自动提出/筛选候选，由人决定晋级。本文不替项目决定一个尚未验证的数值门槛。

## 9. 推荐的交付顺序

### 第一阶段：完成可审查任务，而不是仅写问题

- 人审 30–50 个独立种子，以证据解释和预算更新为主，保留成功与对照任务。
- 小型真实目录快照、工具/RAG fixture、初始 Session 与画像状态。
- 一份逐项验收规则，明确硬约束、软偏好、未知和合法替代结果。
- 评分器校准样本和误判记录。
- 用当前 Java Agent 与真实目标模型跑基线，确认 Skill 加载和工具轨迹可观测。

### 第二阶段：证明能筛出有用候选

做一次受控 Skill 修改，配对跑旧版和候选，逐条解释修复与退化。先判断评分系统是否测到了预期能力，失败是否来自 Skill，而不是默认整体分数就是有效 reward。

### 第三阶段：扩大覆盖并受控自动迭代

逐步补全五类购物 Skill、Session 多轮、界面与工具故障；形成独立选择和锁定测试，增加新的真人任务并校准模拟器。稳定后开放自动候选筛选和接受。真人满意度、选择意愿或线上反馈用于检查离线改善能否迁移；历史未点击商品不能直接一律当作用户不喜欢。

第一轮是否成立，应能回答：任务有解吗；标签符合产品目标吗；合法输出会被接受吗；明显错误会被拒绝吗；两版是否真的执行不同 Skill；运行环境与数据是否一致；修复了什么、破坏了什么。
