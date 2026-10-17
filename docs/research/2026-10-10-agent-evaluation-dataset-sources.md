# 从零形成 RS_agent 评测集：一手资料研究

更新时间：2026-10-10。资料范围：研究论文、作者官方仓库、Google Research 和 Anthropic 官方工程/研究说明。本文是网络资料专题；本地实现是否支持这些方案，以主研究笔记的代码核对为准。文中的规模、字段和操作步骤若标为“建议”，属于针对项目的设计推论，不是论文验证过的统一标准。

## 1. 首先形成什么

自进化需要的不仅是一批问题，还需要可复现的任务环境和可信的判定标准。任务应包含输入、初始状态、可用工具与数据、成功条件；执行后保留轨迹和最终状态。客服 Agent 自称“已经退款”与数据库中实际有退款记录，是两件不同的事。Anthropic 建议从 20–50 个真实失败或已有手工检查起步，同时覆盖行为应发生与不应发生的场景；先验证任务和评分是否合理，再扩大规模。[Anthropic：Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

**对项目的推论：**先建立“固定上下文下的行为任务”，随后增加可分支的多轮任务。不能把“输出中出现推荐商品”直接等同于“推荐成功”；也不能要求所有含糊输入一律追问，必须先确认产品允许哪些有效行为。

## 2. 最值得借鉴的来源

| 来源 | 已核实的内容 | 对 RS_agent 的用途与边界 |
|---|---|---|
| [τ-bench 论文](https://arxiv.org/html/2406.12045v1) | 手工设计 schema/API；LM 辅助生成数据库；人工编写与核验情境；用户模拟器与 Agent 交互，比较终态数据库；重复试验统计可靠性 | 借任务结构、初态重置和结果验收。航空/零售售后任务不能直接证明推荐质量；唯一数据库终态假设不适合所有开放式推荐 |
| [ConvApparel 正式论文，EACL 2026](https://aclanthology.org/2026.eacl-long.244/) | 人类与推荐 Agent 的服装购物对话，good/bad 两类系统，逐轮用户体验标注；用统计对齐、Human-Likeness Score、反事实测试检验模拟器 | 目前与商品推荐最贴近的资料之一；可以借标注方法与失败场景，迁移到中文/其他品类仍需核验 |
| [Google 官方数据卡](https://huggingface.co/datasets/google/ConvApparel) | 英文、CC-BY-4.0；鞋、外套、上装、下装；提供会话、每轮文本/商品及本人 ratings；存在原版和 V2 ZIP | 数据可获取；不是仅有论文。公开数据容易被模型见过，适合作为外部诊断材料，不能单独作为隐藏验收集 |
| [CRSArena-Dial 官方仓库](https://github.com/iai-group/crsarena-dial) | 474 条用户与 9 个推荐系统的对话，用户满意度和匿名系统成对比较反馈，开放/受控两种众包收集 | 借真实用户反馈、盲评、平局机制；不能把其他系统/领域的历史胜负标签直接贴到我们新输出上 |
| [PEPPER，EMNLP Findings 2025](https://aclanthology.org/2025.findings-emnlp.1067/) | 指出预装目标商品的模拟器会让互动退化为猜答案；采用 target-free 用户模拟，评价偏好探查过程 | 推荐结果应允许多个可接受商品，区分硬约束与软偏好，避免只有“猜中某 ID”才得分 |
| [UserSimCRS v2 论文](https://arxiv.org/html/2512.04588v2)、[官方 toolkit](https://github.com/iai-group/UserSimCRS) | 提供 agenda-based、single/dual-prompt 模拟器；推荐相关性、风格、流畅性、连贯性、满意度，以及成功推荐轮比例和按对话长度归一的收益 | 参考多轮任务接口和评测维度；论文发现不同模拟器甚至会改变系统排名，模拟满意度不能直接视为真人满意度 |
| [How Reliable is Your Simulator?](https://arxiv.org/html/2403.16416v1) | 发现历史对话及模拟器回复中的信息泄漏会抬高推荐结果；历史质量影响大；单一 prompt 很难完全约束模拟器 | 使用模拟器前，先检查是否泄漏目标、编造偏好、过度配合 |
| [NAACL 2024：Evaluating LLMs as Generative User Simulators](https://aclanthology.org/2024.naacl-long.83/) | 分五项检验模拟用户：选择谈论的商品、二元偏好、开放偏好、请求推荐、反馈；观察与真人行为偏离 | 先评模拟器，再使用模拟器评 Agent。语言自然只是其中一个条件 |
| [MT-Bench / Chatbot Arena 论文](https://arxiv.org/html/2306.05685v4) | 分析位置、长度、自我偏好及推理局限；成对评分交换顺序可暴露位置偏差 | 评分需要盲评、位置交换、人工参照；大模型裁判不是天然真值 |
| [Generalization in Adaptive Data Analysis and Holdout Reuse](https://arxiv.org/abs/1506.02629) | 反复根据同一 holdout 的结果选择下一假设，会过拟合 holdout 本身 | Skill 优化循环里反复使用的 selection/dev 不是永久的最终证明；应另留锁定测试和新的时间窗口 |
| [Anthropic Bloom](https://www.anthropic.com/research/bloom) | 从目标行为说明与示例出发，经理解、情境构造、互动和评分生成行为评测 | 可借自动发现/生成挑战场景的流程；Bloom 面向行为评测，不能替产品团队定义什么叫好推荐 |

## 3. 如何从真实轨迹变成任务

### 3.1 两种任务必须区分

**固定上下文的下一步任务（建议先做）：**从真实 Session 中截取某个 Turn 之前的用户输入、已知偏好、历史信息和工具可见事实，让旧版和候选 Skill 分别生成下一步。验收的是当前信息下的行动质量，例如是否尊重预算、是否重复询问已知信息、是否引用不存在的事实。标签由当时可见信息与明确产品要求决定，不能用后续用户才披露的条件反过来判错。

**可分支的多轮任务（随后补充）：**保留初始场景与用户目标，但用户根据 Agent 的新动作反馈。不能在 Agent 已经换了问题或商品后，机械重放原日志的下一条用户话语；这种历史后续不再属于当前对话路径。可从 agenda-based 状态/偏好控制开始，让 LLM 只负责表达不同措辞，之后再引入更自由的模拟器。这是基于 UserSimCRS 模块化模拟方式的工程建议，不是“规则模拟等同于真人”的结论。[UserSimCRS v2 §4.2–4.3](https://arxiv.org/html/2512.04588v2)

### 3.2 样本从哪些地方来

建议同时收集四种来源：已记录的真实失败；真实成功与日常任务；产品负责人写出的验收情境；真实样本的受控变体。成功样本能检验修改是否破坏已有能力，失败样本提供改善方向。先由人审少量种子，再让模型归类和提出相邻任务，而不是从某一版 Skill 的规则直接大量生成“考试答案”。

若目前没有足够线上用户，建议由团队成员按自然需求实际使用系统，保存完整输入/工具结果/输出，再逐轮记录满意或不满的原因。ConvApparel 的 good/bad 两种推荐环境与本人体验标注说明，仅收集理想成功对话会错过真实负面反馈；我们可用现有不同版本及故障 fixture 收集差异，不必在线故意伤害用户体验。[Google Research：ConvApparel 的采集与验证](https://research.google/blog/convapparel-measuring-and-bridging-the-realism-gap-in-user-simulators/)

### 3.3 建议的任务记录

```yaml
id: budget_feedback_001
family_id: real_session_017_budget_correction
source: human_dogfood
capability: feedback_adaptation
split: development
input:
  conversation_prefix: "推荐商品后，用户说：太贵了，最多 300"
  known_constraints: {category: shoes, budget_max: 300}
environment:
  catalog_fixture: catalog_v1
  tool_fixture: recommend_feedback_v1
oracle:
  hard_constraints:
    - "再次推荐的商品都来自可见候选集"
    - "再次推荐不包含价格大于 300 的商品"
    - "不能把降价或库存变化写成已证实的事实"
  quality_dimensions:
    - "下一轮行为是否回应预算反馈"
    - "是否保持仍然有效的其他用户约束"
  acceptable_outcomes:
    - "推荐符合约束的候选商品"
    - "无可用商品时说明没有匹配结果，并提出合理放宽条件"
annotation:
  reviewer: domain_reviewer_01
  policy_version: recommendation_policy_v1
  status: reviewed
```

这里的 `oracle` 应是期望事实/约束和可接受结果，不是固定措辞、固定商品或固定全套工具调用顺序。对于不可替代的业务动作和系统协议，可以单独验工具调用或终态；正常推荐路径应允许有效替代方案。τ-bench 的目标标注仅供模拟与评测、不会暴露给被测 Agent，也值得沿用。[τ-bench Figure 2 与 §4.2](https://arxiv.org/html/2406.12045v1)

## 4. 合成变体应改变什么

建议每个真实种子只生成少量有意义的变体，并保留 `family_id`：

- 信息变化：已知/未知预算、已有/没有画像、画像与当前请求冲突。
- 约束变化：从“300 以内”改成“300 左右”，区分硬上限和软偏好；从有解改成 catalog 无解。
- 反馈变化：否定价格、否定颜色、否定品类；明确纠正与模糊不满分开。
- 表达变化：短句、错字、代词、省略、中文口语；这些变体通常应保留同一决策语义。
- 环境变化：工具为空、超时、返回残缺、RAG 证据互相冲突；检查是否承认未知或提出下一步。

用于产品策略评测时，还需要成对任务：一个应澄清、一个无需澄清；一个应读画像、一个已有充分当前约束；一个有证据可解释、一个证据不足。上述具体覆盖维度是项目建议。自动场景构造可借 Bloom，但正式进入验收集前仍需验证情境可解、标签有依据。[Bloom 方法说明](https://www.anthropic.com/research/bloom)

## 5. 推荐和对话应如何判分

建议先保留分项，不立即压成单个“大综合分”：

1. **事实与约束检查：**商品 ID 是否存在、是否在候选集、预算/品类/禁忌是否满足；事实声明是否有 catalog/RAG 支持；工具失败后是否虚构成功。尽量用程序判断。
2. **策略与交互检查：**是否合理澄清、是否重复提问、是否保留用户纠正、是否清楚交代无解。用有锚点的 rubric 和必要的人工/模型判定。
3. **完成与效率：**在允许轮数内得到可接受推荐/解释，轮数、工具次数、token、耗时单独记录。多轮任务的“可接受”应由明确偏好/约束或真人反馈提供依据。

UserSimCRS v2 的 SRRR 是成功推荐轮比例，RDL 是接受推荐数除以对话长度；两者可帮助观察交互效率，但依赖接受/拒绝意图的正确识别，不应因为模拟用户一句“谢谢”就自动判成功。[UserSimCRS v2 §4.6](https://arxiv.org/html/2512.04588v2)

对公开电影/服装数据，可以借对话结构与标注。对 RS_agent 的商品推荐，建议用一个小型固定 catalog 定义“满足硬约束的候选集合”，允许集合内多个商品及合理的不同排序；软偏好另标等级或真人成对偏好。PEPPER 对目标商品预编码导致“猜答案”的批评，支持避免给所有任务设唯一标准商品。[PEPPER 正式论文](https://aclanthology.org/2025.findings-emnlp.1067/)

## 6. 先验证裁判，再让裁判筛 Skill

建议准备独立的裁判校准样本：真人认可输出、真人否定输出及故意变坏的输出。例如把商品改成不存在 ID、预算改超标、删除关键证据、加长空话、忽略用户否定。程序检查应稳定拒绝这些错误；语义裁判应给出可定位的证据。

对需要模型判断的维度，先让两名了解产品的人独立标注一批输出，记录分歧并细化 rubric；随后与候选模型裁判比较，分别看误放行和误拒绝，不能只看整体一致率。成对比较隐藏版本身份并交换 A/B 位置，不一致则标记人工复核或未知。这是工程建议；MT-Bench 的研究确实显示交换位置会改变部分判决，并讨论长度、自我偏好和有限推理能力，但不能据此宣称某一裁判天然可靠。[MT-Bench §3.3–3.4](https://arxiv.org/html/2306.05685v4)

用户模拟器也需独立校准：给同一用户档案分派预算、品类、拒绝原因和有限耐心，检查是否前后矛盾、泄漏隐藏目标、莫名接受不符合约束的商品。推荐领域已有论文直接观察到用户回复泄漏和 prompt 控制不足。[How Reliable is Your Simulator?](https://arxiv.org/html/2403.16416v1)；[NAACL 2024 模拟用户五项测试](https://aclanthology.org/2024.naacl-long.83/)

ConvApparel 的统计对齐及反事实验证可用于后续检查“模拟用户面对好/差输出是否像真人一样反应”。数据来自英文服装和受偿参与者；迁移到中文、多品类、真实购买用户，仍有分布差异。可下载不意味着已经适配，也没有证据证明采用该数据就能直接改善 RS_agent。[ConvApparel 正式论文](https://aclanthology.org/2026.eacl-long.244/)；[Google 官方数据卡](https://huggingface.co/datasets/google/ConvApparel)

## 7. 划分、复现与更新

建议按真实会话/问题族划分优化集、候选选择集、锁定测试集，所有同源改写归同一 split；足够数据后增加时间后移的新真实任务。先 split 种子、再做合成扩增，以免原句在 train、改写句在 test。评分规则、catalog、画像与工具 fixture 都应版本化，每次试验重置状态；候选与旧版用同样的任务和环境。

可以给优化器完整训练轨迹；selection 返回受限的对比结果；锁定测试不用于改 Skill。若人或优化器检查了测试失败并依此修改，这些任务转为已知回归任务，再补新任务作为未知测试。反复自适应查询同一 holdout 会过拟合，是已有理论结果；“隐藏测试”不能永久重复使用而仍被当成未见证明。[Dwork 等：Generalization in Adaptive Data Analysis and Holdout Reuse](https://arxiv.org/abs/1506.02629)

建议报告逐项修复/退化、分能力通过率和重复运行波动，候选接受门槛预先确定，不因候选表现临时修改。开始时可用几十个任务发现明显大问题；它们不足以证明 1–2 个百分点的小提升。多轮推荐最关键的成功/失败任务可重复 3 次作为初步可靠性检查，具体样本量和重复数是项目预算选择，不是通用统计保证。τ-bench 的 pass^k 衡量多次运行全部成功的概率，适合观察用户面向的稳定性，与“多次只要成功一次”的 pass@k 不同。[τ-bench §3、§5](https://arxiv.org/html/2406.12045v1)

## 8. 建议的第一批可审查交付物

建议先产出 30–50 个经人审任务、一个小型固定 catalog/画像/证据 fixture、一份分项判定规则，以及一份人工标签与裁判比较报告。样本来源和比例是暂定计划，随后按真实使用频率修订。最低验收应回答：每条任务可解吗、标准符合产品意图吗、旧版和候选是否确实执行 Skill、明显坏输出能否被拒绝、同一家族是否跨 split、不同运行是否出现无法解释的波动。

第一轮优化应只选一个可客观验证的能力切片，例如“用户纠正预算后，新推荐仍遵守约束”或“解释不编造证据”。某个切片形成可靠 signal 后，再扩展到澄清策略、多轮交互和真实满意度。裁判有疑问或产品规则冲突的任务应进入待审核池，不能同时让它们支配自动 Skill 接受。

## 9. 外部数据的具体获取核查

- [ConvApparel 文件列表](https://huggingface.co/datasets/google/ConvApparel/tree/main)：原版 `ConvApparel.zip` 约 28.1 MB，V2 ZIP 约 27.9 MB；数据卡列出会话和每轮商品、ratings 字段；在线 viewer 可能报结构错误，应从 ZIP 读取并按版本选择。此次未下载或重新分配标签。
- [CRSArena-Dial](https://github.com/iai-group/crsarena-dial)：官方仓库列出 open/closed 对话 JSON 及 votes CSV，可以用于观察真实反馈和做外部诊断。
- [PEPPER 官方仓库](https://github.com/happysnail06/PEPPER)：作者提供实现和 prompt，README 部分数据/模型指向 Google Drive；本文核实链接与仓库存在，未检验外部文件权限、完整性或复现实验。
- [UserSimCRS](https://github.com/iai-group/UserSimCRS)、[ECIR 2026 案例仓库](https://github.com/iai-group/UserSimCRS-ECIR-2026)：可参考配置、已生成的模拟对话和评分结果；不能默认接入就能得到针对本项目有效的用户模型。

