# SkillOpt：自我进化智能体技能的执行策略研究

更新时间：2026-07-19  
研究对象：[Microsoft SkillOpt 官方仓库](https://github.com/microsoft/SkillOpt)、[arXiv 论文 2605.23904 v2](https://arxiv.org/abs/2605.23904)  
代码核对基准：main 分支提交 [b860a5c](https://github.com/microsoft/SkillOpt/commit/b860a5cf88ce75e2bd02ca981ac21fb28cffba83)，提交时间 2026-07-18 17:28:47 UTC。  
资料边界：只采用论文、Microsoft 官方仓库、源码、配置和发布说明；本文没有重新跑数亿 token 的论文实验，因此实验数字均是对作者报告的复述与分析，不是独立复现结果。

## 结论摘要

SkillOpt 最值得记住的不是“让智能体自己随便改提示词”，而是：

> 把一份可部署的自然语言技能文档当作冻结智能体的外部参数；让另一个优化器模型从有分数的执行轨迹中提出小步编辑，再用独立验证集决定是否接受。

因此它更准确地说是一个**受控的文本空间黑盒优化器**：

1. 被适配的目标模型、工具环境和评分器保持固定；
2. 唯一持续训练的状态是一份 Markdown 技能文档；
3. 优化器模型把失败/成功轨迹转成结构化的增、删、改编辑；
4. 每步最多接受有限数量的编辑，形成“文本学习率”；
5. 候选技能只有在选择集分数严格提高时才进入主线；拒绝的编辑反而成为后续负反馈；
6. 最后部署的是静态的 best_skill.md，不需要在每次推理时再调用优化器模型。

这套设计把“反思—自改”从一次性生成，变成了有训练集、选择集、测试集、步长、检查点和回滚语义的优化流程。[论文摘要与方法概览](https://arxiv.org/pdf/2605.23904#page=1)；[当前训练循环文档](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/docs/guide/training-loop.md)

论文的主结果很强：在作者测试的 52 个“模型 × 基准 × 执行环境”单元中，SkillOpt 均为最好或并列最好；GPT-5.5 相比无技能基线，直接对话、Codex、Claude Code 三种环境的平均绝对提升分别为 23.5、24.8、19.1 个百分点。[论文表 1 与 §4.1](https://arxiv.org/pdf/2605.23904#page=7)

但这不是免费午餐。训练一项技能需要可靠的自动评分、反复 rollout 和额外优化器调用；论文六个代表性 GPT-5.5 训练任务单项消耗约 20.8M–213.8M token，且论文表格主要报告点估计，没有给出多随机种子置信区间。它适合**高频、可验证、可复用**的任务，不适合一次性或无法可靠评价的开放任务。[论文表 6](https://arxiv.org/pdf/2605.23904#page=14)；[论文局限性](https://arxiv.org/pdf/2605.23904#page=20)

## 1. 它到底在解决什么问题

### 1.1 目标不是训练模型权重，而是训练“怎么做事”

论文把 skill 定义为执行前注入上下文的自然语言策略，它可以包含流程、领域启发、工具使用政策、输出约束和常见失败模式。目标模型记为 M，执行环境/代理框架记为 h，任务为 x，技能为 s；一次运行产生轨迹 τ 和标量奖励 r：

    (τ(s), r(s)) = h(M, x, s),  r(s) ∈ [0, 1]

M 和 h 均冻结，系统优化的是 s。训练集用于产生编辑证据，选择集用于决定候选技能是否进入主线，测试集只在最后报告。[论文 §3.1](https://arxiv.org/pdf/2605.23904#page=4)

这意味着 SkillOpt 主要学习的是**程序性知识**，例如：

- 先检查哪些证据，再调用什么工具；
- 如何维护任务状态，避免循环；
- 遇到表格、文档或公式时按什么顺序验证；
- 最终答案必须采用什么格式；
- 哪些看似合理的行为会稳定导致评分失败。

它不是知识库训练，也不直接把新事实写回模型权重；更接近“给同一位执行者训练一本越来越有效的作业手册”。[论文引言](https://arxiv.org/pdf/2605.23904#page=1)

### 1.2 为什么普通的自我反思不够

手写技能、一次性 LLM 生成技能，以及无约束的“失败后重写整个提示词”有三个共同问题：

- 单个失败样本容易诱发只对该样本有效的补丁；
- 大段重写会抹掉已有效的规则，产生灾难性遗忘；
- 语言上听起来合理的反思，未必真的提高目标模型的任务分数。

SkillOpt 的回答是把“生成修改”和“批准修改”分开：优化器只负责提案，选择集评分才拥有合并权。该思路在源码中也是纯决策函数：候选分数必须严格大于当前分数才接受，等分直接拒绝。[验证门源码](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/evaluation/gate.py#L135-L225)

## 2. 深度学习类比：有用，但不是字面等价

| 深度学习概念 | SkillOpt 对应物 | 实际含义 |
|---|---|---|
| 模型参数 | Markdown 技能文档 | 唯一持续变化、最终部署的状态 |
| 前向传播 | rollout | 目标模型带当前技能执行一批任务 |
| 损失/奖励 | 基准评分器 | 精确匹配、可执行检查、任务成功率等 |
| 反向传播 | 轨迹反思 | 优化器阅读成功和失败轨迹 |
| 梯度 | 结构化文本编辑 | 增加、插入、替换、删除规则 |
| 梯度聚合 | 编辑合并 | 去重、消冲突、统计支持度 |
| 梯度裁剪 | 排序并截取前 L 条 | 控制每步最多改变多少项 |
| 学习率 | 编辑预算 L | 每步最多应用的编辑条数 |
| 学习率调度 | constant/linear/cosine/autonomous | 随训练进度改变编辑预算 |
| 验证集 | selection split | 接受或拒绝候选技能 |
| 动量/慢变量 | slow update | 跨 epoch 保留长期规律 |
| 元学习记忆 | meta skill | 只指导优化器怎样写更好的编辑 |
| 检查点 | skill 快照与 best_skill.md | 可恢复、可审计、可回滚 |

官方文档给出了完整映射。[深度学习类比文档](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/docs/guide/dl-analogy.md)

这只是工程控制论类比，不是真正的可微优化：

- 没有数学梯度，编辑方向由另一个 LLM 语义判断；
- “学习率”限制的是编辑条数，不是语义距离；一条替换仍可能很长；
- 选择集门控保证的是固定选择集上的单调改进，不保证真实分布或测试集单调；
- 当前代码还支持整篇重写模式，这时“有界小步”的类比会进一步变弱。[编辑模式源码](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/optimizer/update_modes.py)

所以其真正创新不是“文本也能做 SGD”，而是把成熟训练系统中的**证据批处理、步长约束、独立选择、负反馈、检查点和双时间尺度**移植到文本策略优化。

## 3. 核心算法：一轮怎样运行

输入包括初始技能 S₀、冻结目标模型、优化器模型、执行适配器、训练/选择/测试三份数据，以及可输出标量分数的评价器。

### 3.1 六阶段快循环

    当前技能 S_t
       ↓
    1. Rollout：在训练批次上执行并记录轨迹与分数
       ↓
    2. Reflect：失败与成功分别分成小批次，由优化器分析
       ↓
    3. Aggregate：分层合并编辑，失败修复优先
       ↓
    4. Select：按预期影响排序，只保留预算 L_t 内的编辑
       ↓
    5. Update：应用增/插/替/删，得到候选技能 S'
       ↓
    6. Gate：在选择集上重跑
       ├─ score(S') > score(S_t)：接受
       └─ score(S') ≤ score(S_t)：拒绝，并记录为负反馈

源码中的训练器正按 rollout、reflect、aggregate、select、update、evaluate 六阶段执行，并保存每一步的中间产物。[训练器 rollout/reflect](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/engine/trainer.py#L1102-L1166)；[训练器 aggregate/select](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/engine/trainer.py#L1235-L1321)；[训练器 update/gate](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/engine/trainer.py#L1323-L1550)

### 3.2 反思为什么同时看失败和成功

失败小批次寻找反复出现的缺口，如错误工具、错误证据源、遗漏验证或格式错误；成功小批次保护已经有效但尚未写入技能的行为。每个分析器被要求只总结跨多个轨迹出现的规律，禁止硬编码单个任务值，并输出 JSON 编辑，而不是自由散文。[失败分析器提示](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/prompts/analyst_error.md)；[成功分析器提示](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/prompts/analyst_success.md)

反思引擎先按 hard score 分离失败与成功，再各自切成 minibatch，并行调用优化器。这比“一条轨迹一次反思”更倾向于提取共性，而不是生成轶事式补丁。[反思引擎源码](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/gradient/reflect.py#L472-L627)

### 3.3 合并和排序为什么分成两步

聚合阶段先分别合并失败编辑、成功编辑，再进行一次最终合并；冲突时失败修复优先，同时保留支持次数和来源。随后另一次优化器调用按“系统性影响、互补性、通用性、可执行性”排序，截取前 L 条。[分层聚合源码](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/gradient/aggregate.py#L143-L253)；[排序提示](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/prompts/ranking.md)；[截取实现](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/optimizer/clip.py#L25-L104)

这个拆分很重要：聚合回答“有哪些不重复、无冲突的候选方向”，排序回答“有限变更预算应该花在哪里”。因此 L 不只是长度限制，也是变更风险预算。

### 3.4 拒绝不是浪费，而是训练数据

被拒候选的编辑内容、修改前后分数和仍存在的失败模式，会进入 epoch 内的 step buffer。后续反思能看到“什么已经试过且使分数下降”，从而避免反复走同一条错误路线。[拒绝缓冲区写入](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/engine/trainer.py#L1554-L1586)；[论文 §3.5](https://arxiv.org/pdf/2605.23904#page=6)

这相当于把负面实验结果变成优化器记忆，是本方法比普通自我修订稳定的关键之一。

### 3.5 epoch 边界的慢更新与元技能

快循环只看当前批次；epoch 结束时系统让上一 epoch 技能和当前技能在同一组训练任务上执行，分成四类：

- improved：以前错、现在对；
- regressed：以前对、现在错；
- persistent failure：一直错；
- stable success：一直对。

slow update 把跨 epoch 的稳定规律写进技能文档受保护区域，面向目标模型；meta skill 则总结“什么类型的编辑有效/有害”，只放进后续优化器的提示上下文，不随部署技能发布。二者分别是**执行者长期记忆**和**优化者策略记忆**，不应混为一谈。[论文 §3.6](https://arxiv.org/pdf/2605.23904#page=6)；[慢更新提示](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/prompts/slow_update.md)；[元技能提示](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/prompts/meta_skill.md)

## 4. 技能如何表示与部署

### 4.1 核心对象是一份可读 Markdown

技能文档不是向量，也不是隐藏状态，而是人可以审计、版本控制和手工修订的 Markdown。初始技能可以为空、人工种子或相关任务已经训练好的技能；最终只导出验证最优的 best_skill.md。[技能文档指南](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/docs/guide/skill-document.md)

当前源码的原子编辑类型为：

- append：在正文末尾追加；
- insert_after：在精确目标文本后插入；
- replace：替换第一次匹配的目标；
- delete：删除第一次匹配的目标。

每条编辑还可携带来源、支持次数和合并层级；Patch 是多条 Edit 加一段推理说明。[类型定义](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/types.py#L23-L101)

编辑应用器会生成逐条 applied/skipped/error 报告，且禁止普通编辑改动受保护的慢更新或附录区域。这使每次 best_skill.md 变化都可追踪，而不是只留下重写后的最终文本。[编辑应用源码](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/optimizer/skill.py#L85-L201)

### 4.2 “零推理时额外调用”的准确含义

部署时不再调用优化器模型，也不改目标模型权重；只是把 best_skill.md 注入目标模型上下文。它仍会增加上下文 token，并非整个推理零成本。论文六项最终技能为 379–1,995 token，中位数约 920 token。[论文 §4.4 与表 6](https://arxiv.org/pdf/2605.23904#page=14)

### 4.3 三种执行环境使用同一技能格式

- Direct chat：把技能放进 system/developer instruction；
- Codex：为每个任务写出 SKILL.md，执行 CLI，再把紧凑轨迹摘要交给优化器；
- Claude Code：采用相似的 workspace 契约。

统一文本格式是跨执行环境迁移成立的前提。ALFWorld 需要持久具身环境交互，因此论文没有在 Codex/Claude Code 两行中评测它。[论文 harness 说明](https://arxiv.org/pdf/2605.23904#page=9)

## 5. 训练、评估与可复现流程

### 5.1 数据隔离

论文形式化使用三份数据：

- train：产生 rollout 和编辑提案；
- selection/validation：反复做接受/拒绝与最优技能选择；
- test：训练期间锁定，最后一次评估泛化。

当前代码把 selection 称为 valid_seen、test 称为 valid_unseen；最终同时测初始 S₀ 和 best_skill，便于计算真实增益。[论文 §3.1](https://arxiv.org/pdf/2605.23904#page=4)；[最终评估源码](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/engine/trainer.py#L2091-L2203)

论文中的拆分比例需要谨慎核对：表 2 的 caption 明确说其训练规模实验固定采用 4:1:5 的 train/selection/test 比例，而附录 C 又说“未另行说明时”默认采用 2:1:7。二者可以理解为表 2 使用了专门覆盖配置、附录描述全局默认，但论文没有把每个主表单元最终采用哪一种比例全部逐项展开。因此复现时应以发布的 benchmark manifest、固定配置和具体实验记录为准，不能把任一比例当成所有结果的统一设置。[论文表 2 caption](https://arxiv.org/pdf/2605.23904#page=8)；[论文附录 C](https://arxiv.org/pdf/2605.23904#page=20)

### 5.2 论文默认训练参数

论文默认值为：

- 4 个 epoch；
- rollout batch size 40；
- reflection minibatch size 8；
- 16 个并行分析 worker；
- merge batch size 8；
- 文本学习率 L=4，cosine 衰减，最小 L=2；
- 严格选择门：只有严格更高才接受，等分拒绝；
- 每 epoch 20 个配对样本做 slow update；
- patch 编辑模式；
- 最多 3 轮分析器细化；
- 目标和优化器调用默认 medium reasoning。

LiveMathematicianBench 和 ALFWorld 因数据规模/环境特点使用各自批量设置。[论文实验设置](https://arxiv.org/pdf/2605.23904#page=8)

当前基础配置仍保留大部分值，但增加了更多后论文选项，如 hard/soft/mixed 门控、autonomous 学习率、整篇重写、semantic density 和 skill-aware reflection。[当前基础配置](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/configs/_base_/default.yaml#L59-L103)；[当前配置参考](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/docs/reference/config.md)

### 5.3 六个基准覆盖的能力

| 基准 | 主要能力 | 执行特征 |
|---|---|---|
| SearchQA | 搜索上下文问答 | 单轮、精确答案 |
| SpreadsheetBench | 表格操作与代码生成 | 最多约 30 轮，真实 openpyxl/pandas |
| OfficeQA | 企业文档工具问答 | 最多约 24 次工具调用 |
| DocVQA | 文档视觉问答 | 多模态证据对齐 |
| LiveMathematicianBench | 数学选择题/定理推理 | 强格式与推理约束 |
| ALFWorld | 具身序列决策 | 最多约 50 步的持久交互 |

基准范围和评分协议见论文实验设置与附录。[论文 §4 与附录 C](https://arxiv.org/pdf/2605.23904#page=6)

还有一个文本口径差异：附录 C 的 benchmark 描述额外出现了 SealQA，但摘要、§4 设置和主结果表只报告上述六个基准，也没有 SealQA 对应的主表分数。本文因此把“六个 benchmark”限定为论文的 headline evaluation suite，不把附录中的 SealQA 名称计作已报告的第七项主实验。[论文主实验设置](https://arxiv.org/pdf/2605.23904#page=6)；[论文附录 C](https://arxiv.org/pdf/2605.23904#page=20)

### 5.4 输出和恢复

训练过程会保存 history.json、runtime_state.json、best_skill.md、逐步技能快照、候选技能、编辑应用报告、选择集结果、slow update 和 meta skill 日志；同一命令可从完成步骤继续。这个“把优化历史做成一等产物”的工程选择，是技能可审计和可回滚的重要部分。[官方训练文档](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/docs/guide/training-loop.md)；[训练器状态保存](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/engine/trainer.py#L1605-L1618)

### 5.5 当前仓库的复现材料并非“开箱即跑全部论文”

仓库现在提供六个基准的轻量 ID/路径 split manifest，以及六份 GPT-5.5 论文对齐技能 checkpoint。但除 ALFWorld 路径清单外，大多数 manifest 不含完整题目、答案、文档、图片或工作簿；使用者仍需从上游数据源 materialize 原始数据，并准备相应模型 API/CLI 环境。[数据清单说明](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/data/README.md)；[论文技能 checkpoint 说明](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/ckpt/README.md)

## 6. 实验到底说明了什么

### 6.1 GPT-5.5 直接对话主结果

| 基准 | 无技能 | SkillOpt | 绝对提升 |
|---|---:|---:|---:|
| SearchQA | 77.7 | 87.3 | +9.6 |
| SpreadsheetBench | 41.8 | 80.7 | +38.9 |
| OfficeQA | 33.1 | 72.1 | +39.0 |
| DocVQA | 78.8 | 91.2 | +12.4 |
| LiveMathematicianBench | 37.6 | 66.9 | +29.3 |
| ALFWorld | 83.6 | 95.5 | +11.9 |
| 六项平均 | 58.8 | 82.3 | +23.5 |

作者还计算了一个“逐单元挑选六种竞争方法中最好者”的 oracle 基线，其平均为 76.9；SkillOpt 仍高 5.4 个百分点。竞争方法包括人工技能、一次性 LLM 技能、Trace2Skill、TextGrad、GEPA，以及 harness 场景中的 EvoSkill。[论文表 1 与 §4.1](https://arxiv.org/pdf/2605.23904#page=7)

这些数字最明显的模式是：**越依赖严格流程、工具使用和输出格式，收益越大**。SearchQA 和 DocVQA 的无技能起点已经较高，增益较小；表格、OfficeQA 和数学任务的流程纪律空间更大。[论文 §4.1](https://arxiv.org/pdf/2605.23904#page=10)

### 6.2 模型规模和执行环境

直接对话中，SkillOpt 在作者评测的 GPT-5.5、GPT-5.4、GPT-5.4-mini、GPT-5.4-nano、GPT-5.2、Qwen3.5-4B、Qwen3.6-35B-A3B 七个目标模型上，六基准平均绝对提升约 17.6 个百分点。较小模型相对收益尤其明显，符合“外部程序性规则补足权重中欠缺执行纪律”的解释。[论文 §4.1](https://arxiv.org/pdf/2605.23904#page=10)

在 GPT-5.5 的工具执行环境中：

- Codex 五基准平均比无技能高 24.8 个百分点，比 EvoSkill 高 14.0；
- Claude Code 五基准平均比无技能高 19.1 个百分点，比 EvoSkill 高 3.2。

因此论文证据不仅来自单轮提示，还来自文件、工具和命令执行循环。[论文表 1](https://arxiv.org/pdf/2605.23904#page=7)

### 6.3 消融结果支持的是“控制结构”，不是某个神奇超参数

三项关键消融（SearchQA / SpreadsheetBench / LiveMath）为：

| 组件 | 完整设置 | 去除后 | 主要变化 |
|---|---|---|---|
| 有界文本学习率 | 87.1 / 77.5 / 61.3 | 84.6 / 75.7 / 57.3 | 三项均降 |
| 拒绝缓冲区 | 87.1 / 77.5 / 61.3 | 85.5 / 72.9 / 58.9 | 表格下降 4.6 |
| meta + slow update | 87.1 / 77.5 / 61.3 | 86.3 / 55.0 / 59.7 | 表格下降 22.5 |

batch、minibatch 和 scheduler 的具体取值相对不敏感；论文表 2 中 constant 甚至在 SearchQA 和 SpreadsheetBench 高于 cosine。更稳妥的结论是“有限步长 + 独立门控 + 拒绝记忆 + 慢变量”有效，而不是“cosine 永远最佳”。[论文表 2、表 3 与 §4.2](https://arxiv.org/pdf/2605.23904#page=8)

### 6.4 迁移实验

- 跨模型：GPT-5.4 上训练的表格/数学技能迁移到 mini、nano 后，四个真实迁移单元均高于无技能基线，增益约 3.0–9.4；
- 跨 harness：Codex 训练的 SpreadsheetBench 技能迁移到 Claude Code，提升 59.7；反向迁移提升 43.6；
- 跨基准：OlympiadBench 技能迁移到 Omni-MATH，在三个模型规模上提升 1.3–3.7。

跨基准收益明显小于同域或跨 harness 收益，说明迁移主要来自通用程序，而不是任何技能都能无损跨域。[论文表 4 与 §4.3](https://arxiv.org/pdf/2605.23904#page=9)

### 6.5 优化器越强越好，但方法不等同于教师蒸馏

作者用 GPT-5.5 强优化器和“与目标模型同规模”的优化器做对比。强优化器在四个单元上都更好，但同规模优化器仍保留强优化器增益的约 56%–74%。这说明更强教师是训练时杠杆，但验证门和循环本身也贡献了相当部分收益；强优化器不会进入部署路径。[论文表 5](https://arxiv.org/pdf/2605.23904#page=13)

### 6.6 学到的规则是什么样

论文案例显示，最终规则以过程纪律为主：

- SpreadsheetBench 从泛化的“用 Python 改表”演化为先检查真实工作簿结构、规范化键/单元格类型、写入评分器能读取的静态结果、保存后重开检查边界和空白；
- ALFWorld 从通用“搜索—拾取—变换—放置”演化为带精确对象身份、已访问位置、进度锁和循环终止条件的有限状态策略；
- OfficeQA 强化证据页、表格、日期、单位绑定和严格答案格式；
- DocVQA 强化问题与具体视觉行/列/字段的对齐。

这些不是训练实例答案，而是可重复执行的规则。[论文 §4.4–4.5](https://arxiv.org/pdf/2605.23904#page=14)

### 6.7 技能很小，但训练并不便宜

六项代表性实验的最终技能只有 379–1,995 token，且仅有 1–4 次候选更新最终被接受；然而单项训练消耗 20.8M–213.8M token，每个测试百分点约 0.6M–46.4M token。六项表中数字合计约 526.7M 训练 token（本文据表 6 求和）。[论文表 6](https://arxiv.org/pdf/2605.23904#page=14)

这揭示了它的经济模型：**离线大量试错，在线廉价复用**。技能被调用越频繁、生命周期越长，训练成本越容易摊薄。

## 7. 局限与应当谨慎解读的地方

### 7.1 论文自己承认的限制

1. 必须有 scored trajectory 和相对可靠的选择集评价。开放式、主观、多目标或人工判断昂贵的任务，需要更强的人类/模型评价器。
2. 虽然部署物很小，训练仍需要大量 rollout 和优化器调用，对一次性任务不划算。
3. 当前方法优化“单域单技能”，不负责构建大型技能库；高度异构领域可能无法装进一个紧凑文档。
4. 技能会吸收训练分布的启发式规则，跨模型、跨 harness、跨任务转移前仍需重新做独立评估。[论文局限性](https://arxiv.org/pdf/2605.23904#page=20)

### 7.2 进一步的技术风险

**选择集也会被自适应过拟合。** 测试集虽不参与训练，但同一个选择集会被每个候选反复查询。严格单调只意味着选择集得分不降，不能证明真实分布不降；选择集小、评分噪声大时尤其明显。当前代码为此增加了 soft/mixed score，但并没有消除自适应选择偏差。[门控指标源码](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/evaluation/gate.py#L10-L22)

**编辑条数不等于真实步长。** L=1 可能只是加一句，也可能替换大段文本。生产实现最好同时限制编辑条数、每条 token 数、总技能长度和受影响章节，并对高风险规则设置人工审批。

**52/52 是“作者所测单元和基线集合”中的结果。** 不应外推为所有模型、任务或所有技能优化算法上的普遍支配；不同 harness 的可用基线也不同，ALFWorld 没有 Codex/Claude Code 单元。[论文表 1 说明](https://arxiv.org/pdf/2605.23904#page=7)

**基线结果对齐不等于训练计算量对齐。** 论文说明各方法使用同一目标模型、测试拆分和 scorer，这能控制评测口径；但没有证明人工技能、一次性 LLM 技能、Trace2Skill、TextGrad、GEPA、EvoSkill 与 SkillOpt 使用了相同训练 token、优化器调用数或墙钟预算。尤其 SkillOpt 表 6 显示了很高的离线计算量，因此“效果最好”和“单位训练成本最好”是两个不同命题。[论文 baseline 协议](https://arxiv.org/pdf/2605.23904#page=9)；[论文表 6](https://arxiv.org/pdf/2605.23904#page=14)

**论文主要报告点估计。** 实验说明了固定数据拆分种子 42，但主表和消融表未报告多次随机运行的均值、方差或置信区间。目标/优化器 LLM 和工具链本身存在随机性，因此接近的分数差不应自动视为统计显著。[论文实验协议](https://arxiv.org/pdf/2605.23904#page=8)

**评价器会塑造技能。** 如果评分器奖励错误格式、捷径或代理指标，验证门会稳定地把这种偏差写进技能。SkillOpt 解决的是“如何可靠优化给定目标”，不是“目标本身是否正确”。

**安全与数据治理问题仍在。** 轨迹可能包含用户数据、工具输出和文件内容；把完整失败轨迹交给外部优化器模型前需要脱敏、权限隔离、保留策略和提示注入防护。论文的性能实验不等同于企业数据治理方案。

## 8. 当前 GitHub 仓库状态：论文与 main 已经不是同一件事

截至 2026-07-19 查询官方仓库：

- 默认分支 main，约 278 次提交；
- GitHub 页面显示约 13.1k stars、1.2k forks，已高于提问中的 12k；
- 精确 API 快照为 13,141 stars、1,226 forks；
- MIT License，Python 3.10+，项目元数据仍标记 Development Status :: 3 - Alpha；
- 最新正式版为 v0.2.0，发布于 2026-07-02；v0.1.0 发布于 2026-06-02；
- 本文核对的 main 已在 v0.2.0 之后继续加入未发布修复与后端能力。

来源：[GitHub 仓库页](https://github.com/microsoft/SkillOpt)、[GitHub 官方 API](https://api.github.com/repos/microsoft/SkillOpt)、[v0.2.0 发布说明](https://github.com/microsoft/SkillOpt/releases/tag/v0.2.0)、[项目元数据](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/pyproject.toml)、[当前 Changelog](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/CHANGELOG.md)

### 8.1 当前仓库有两条产品线

1. skillopt/：论文对应的研究训练框架，负责 rollout → reflect → aggregate → select → update → evaluate。
2. skillopt_sleep/：v0.2.0 新增的夜间离线自进化引擎，从真实编码会话中 harvest、mine、replay，再经验证门 consolidate；另有 Codex、Claude Code、Copilot、Devin、OpenClaw 集成壳。

SkillOpt-Sleep 是论文思想向持续工程代理的延伸，不是论文 52 单元主实验本身。[README 新闻](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/README.md#L11-L28)；[v0.2.0 发布说明](https://github.com/microsoft/SkillOpt/releases/tag/v0.2.0)

### 8.2 一个复现时必须注意的语义差异

论文 §3.6 说 slow update 候选仍要经过选择集门控；但当前 main 的基础配置将 optimizer.slow_update_gate_with_selection 设为 false，即 epoch 慢更新默认强制注入当前技能，最后再做一次选择集评估决定是否晋升为 best。仓库 checkpoint 文档明确说明，论文技能使用 true，而当前 main 默认 false，两种模式可能产出不同结果。[论文 §3.6](https://arxiv.org/pdf/2605.23904#page=6)；[当前默认配置](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/configs/_base_/default.yaml#L73-L86)；[checkpoint 复现警告](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/ckpt/README.md#why-force-accept-vs-gated-slow-update-matters)

源码进一步确认了这条路径：默认分支在 epoch 边界把 slow guidance 强制写入 current_skill、暂不改 best_skill；训练结束前再对 final skill 做一次真实 selection rollout，只有其 gate score 超过既有 best 才晋升。因此它仍保护最终 best 的选择集最优语义，但不再等同于论文所述“每个 slow-update candidate 先过 gate、再进入后续训练状态”。[强制注入实现](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/engine/trainer.py#L1912-L1935)；[最终 selection promotion](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/engine/trainer.py#L2094-L2148)

因此要复现论文语义，不能只说“跑当前默认配置”，至少应：

- 固定仓库 commit/tag；
- 显式设置 slow_update_gate_with_selection: true；
- 使用论文对应 split、评分器、模型版本和 harness；
- 区分论文 patch 模式与后续新增的 rewrite、soft gate、semantic density、skill-aware reflection 等实验性功能。

## 9. 对自研智能体最可复用的启发

### 9.1 把“程序性能力”从模型里外置

不要把每次优化都等同于微调模型。对于稳定领域，执行流程、工具顺序、验证规则和输出契约适合成为独立、可版本化的技能层。这样模型可以升级，技能仍能审计、迁移和回滚。

### 9.2 提议者和裁决者必须分权

让 LLM 读失败轨迹并写改进建议很容易；真正困难的是阻止看似合理但实际有害的建议进入生产。可复用架构应至少有：

- proposal：从证据生成结构化候选；
- evaluator：在隔离数据上评分；
- gate：按明确策略接受、拒绝或回滚；
- artifact store：保存当前、最佳、候选和拒绝记录。

### 9.3 先从可验证任务开始

最适合第一批落地的任务有明确成功标准，例如：

- 单元/集成测试是否通过；
- SQL 或数据管道输出是否与金标一致；
- API schema、文件格式、工作簿单元格是否正确；
- 推荐系统离线指标、约束违规率和延迟是否越过门槛；
- 工具调用是否完成目标且没有越权。

“回答更有帮助”“用户更满意”一类目标若没有可靠评审，先不要全自动自进化。

### 9.4 小步编辑还要加语义预算

可以借鉴 add/replace/delete 和严格门控，但生产系统应比论文更保守：

- 每步 1–3 条编辑；
- 每条和总文档都有 token 上限；
- 禁止修改安全、权限和数据治理区；
- 规则需标注证据、影响范围和版本；
- 高风险变更必须人工批准；
- 选择集不只测平均分，还测安全、延迟、成本和关键回归桶。

### 9.5 把拒绝历史保留下来

失败实验是珍贵资产。每次拒绝至少记录：

- 哪些轨迹触发修改；
- 候选编辑是什么；
- 哪些指标改善、哪些退化；
- 为什么被拒；
- 以后遇到什么证据才值得重试。

这能减少智能体循环犯错，也让人类知道“系统为什么没有采用一个看起来合理的建议”。

### 9.6 快慢双循环值得直接借用

- 快循环：修复当前批次中重复出现的具体问题；
- 慢循环：跨周/跨版本比较长期回归与稳定成功；
- 元记忆：只教优化器如何更好地修改，不污染运行时技能；
- 部署技能：只保留目标模型真正需要的最小规则。

这个分层比把所有反思不断追加到一份越来越长的提示词更可持续。

### 9.7 一个可落地的最小版本

1. 选一个高频、单域、可自动评分的任务；
2. 固定目标模型、工具、系统提示和评价器；
3. 准备互斥的 train/selection/test，测试集训练期间不可见；
4. 每批收集完整轨迹，但先脱敏和裁剪无关内容；
5. 优化器只输出 JSON Patch 风格的 1–3 条局部编辑；
6. 候选在 selection 上必须严格超过当前技能，并通过安全/成本硬门槛；
7. 等分或不确定时拒绝，拒绝记录进入后续上下文；
8. 只发布 validation-best，最后一次用 test 给出真实泛化结果；
9. 全程保存版本、分数、差异和回滚点；
10. 当调用量不足以摊薄训练成本时停止自动优化。

## 10. 最终判断

SkillOpt 的核心思想是成立而且实用的：**智能体技能可以是一层外部、可训练、可验证、可部署的程序性状态**。它最有价值的地方不是新造了一种提示词技巧，而是给“技能自进化”补上了工程纪律：

- 从真实执行轨迹而不是主观反思出发；
- 用小步结构化编辑保护已有能力；
- 用独立选择集而不是优化器自评控制上线；
- 把拒绝、慢更新和元记忆变成显式状态；
- 输出一份小而可审计的静态技能，而不是永久依赖昂贵教师。

同时，应把它看成有适用条件的黑盒策略优化，而不是自动获得持续智能的通用方案。可靠评分、数据隔离、成本摊销、统计稳定性、安全审计和版本固定，决定了它在真实系统里究竟是“自我进化”，还是“把评价器偏差稳定写进提示词”。

## 主要一手资料

- [论文摘要与版本记录](https://arxiv.org/abs/2605.23904)
- [论文 PDF v2](https://arxiv.org/pdf/2605.23904)
- [Microsoft SkillOpt 官方仓库](https://github.com/microsoft/SkillOpt)
- [README（固定提交）](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/README.md)
- [训练器源码（固定提交）](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/engine/trainer.py)
- [验证门源码（固定提交）](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/evaluation/gate.py)
- [默认配置（固定提交）](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/configs/_base_/default.yaml)
- [数据 manifest 说明](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/data/README.md)
- [论文技能 checkpoint 说明](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/ckpt/README.md)
- [v0.2.0 发布说明](https://github.com/microsoft/SkillOpt/releases/tag/v0.2.0)
- [当前 Changelog（固定提交）](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/CHANGELOG.md)
