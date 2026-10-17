# SkillOpt 论文具体如何评测

更新时间：2026-07-19  
研究对象：[SkillOpt 论文 arXiv:2605.23904 v2](https://arxiv.org/abs/2605.23904)、[Microsoft SkillOpt 官方仓库](https://github.com/microsoft/SkillOpt)  
代码核对基准：官方仓库提交 [`b860a5c`](https://github.com/microsoft/SkillOpt/commit/b860a5cf88ce75e2bd02ca981ac21fb28cffba83)  
资料边界：只使用论文和 Microsoft 官方仓库。本文是现有综合研究笔记的“评测协议专题补充”，没有重新运行论文所需的数千万至数亿 token 实验。

## 一句话结论

SkillOpt 的评测并不是“让另一个 LLM 判断回答好不好”，而是：

1. 选择六个具有自动 verifier 的 benchmark；
2. 每条任务执行后，由 benchmark 原生规则给出 `hard ∈ {0,1}`，另可记录 `soft ∈ [0,1]`；
3. 对一个 split 中所有任务的 `hard` 取平均，得到 accuracy / success rate；
4. 训练轨迹来自 train split；候选技能必须在独立 selection split 上使平均 hard score **严格高于**当前技能，等分也拒绝；
5. 最后只把 selection-best 的 `best_skill.md` 放到锁定 test split 上报告成绩。

因此，它的“自动化”成立在一个很强的前提上：**任务必须有可靠、可程序化的结果判定**。论文也明确把 exact match、可执行检查和环境成功信号视为最适用场景；开放式主观任务则需要额外的人类或模型评价器。[论文 §3.1、§3.5](https://arxiv.org/pdf/2605.23904#page=4)；[论文 Limitations](https://arxiv.org/pdf/2605.23904#page=20)

## 1. 评测单位是什么

一次实验固定三个对象：

- frozen target model：真正执行任务的模型；
- harness：直接对话、Codex CLI、Claude Code CLI 或 benchmark 专用环境；
- scorer/verifier：把最终答案、生成文件或环境状态变成标量分数的程序。

唯一持续变化的状态是自然语言技能文档 `s`。对任务 `x`，执行产生完整轨迹 `τ` 和标量奖励 `r ∈ [0,1]`：

```text
(trajectory, score) = harness(target_model, task, skill)
```

train 用来生成候选技能；selection 用来选择候选；test 只用于最终报告。形式上，SkillOpt 从 train 产生的候选集合中选择 selection 平均分最高的技能，再在 test 上取平均。[论文 §3.1](https://arxiv.org/pdf/2605.23904#page=4)

主表的一个 cell 是一个 `(target model, benchmark, harness)` 组合，而不是一次单独问答。一个 cell 的数字是该组合在完整 held-out test split 上的平均 hard score，再乘 100 写成百分数。[论文表 1](https://arxiv.org/pdf/2605.23904#page=7)；[官方平均分实现](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/utils/scoring.py#L7-L23)

## 2. 六个 benchmark、任务和具体 scorer

官方发布的论文 split 固定计数如下；顺序均为 `train / selection / test`。[官方数据 manifest 说明](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/data/README.md#L27-L38)

| Benchmark | 任务形态 | 发布 split | 论文式 hard score | 代码同时记录的 soft score |
|---|---|---:|---|---|
| SearchQA | 给定搜索上下文的单轮抽取式问答 | 400 / 200 / 1400 | 规范化后的 exact match | SQuAD 风格 token F1 |
| SpreadsheetBench | 修改真实 Excel 工作簿，多轮代码/工具执行 | 80 / 40 / 280 | 一个任务的所有 test case 都通过才为 1 | 通过 test case 的比例 |
| OfficeQA | 企业文档问答，最多约 24 次工具调用 | 50 / 24 / 172 | 规范化最终答案 exact match | token F1 |
| DocVQA | 文档图片上的单轮视觉问答 | 107 / 53 / 374 | ANLS 至少 0.999 才为 1 | ANLS partial credit |
| LiveMathematicianBench | 数学多选题推理 | 35 / 18 / 124 | 选项 label exact match | 与 hard 相同 |
| ALFWorld | 具身环境中的多步序列决策，最多 50 步 | 39 / 18 / 134 | 环境 `won == true` | 与 hard 相同 |

### 2.1 SearchQA

模型读入问题和检索上下文，输出 `<answer>...</answer>`；缺少标签时取最后一个非空行。scorer 将答案转小写，删除标点和英语冠词，压缩空白，然后与任一 gold answer 做 exact match。hard 是 EM，soft 是对多个 gold 取最大的 token-level F1；代码还计算 substring match，但主 gate 不使用它。[SearchQA evaluator](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/envs/searchqa/evaluator.py#L1-L100)；[hard/soft 映射](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/envs/searchqa/rollout.py#L242-L252)

### 2.2 SpreadsheetBench

这不是评价回答文案，而是评价**生成后的工作簿**。执行器用 openpyxl/pandas 运行模型生成的操作，然后只比较 gold 指定的 sheet/range 中的 cell value：数值按两位小数量化，日期转 Excel serial day，`""` 与 `None` 可视为相同；不比较格式/样式。一个 benchmark item 可能对应多个 test case，全部通过才 `hard=1`，soft 为通过比例。[SpreadsheetBench cell evaluator](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/envs/spreadsheetbench/evaluator.py#L1-L158)；[任务级 hard/soft 聚合](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/envs/spreadsheetbench/rollout.py#L421-L439)

所以该 benchmark 奖励的是“文件最终状态正确”，不是模型是否声称自己完成了任务。

### 2.3 OfficeQA

模型在本地企业文档/解析页上检索并回答。最终答案先转小写、去逗号和多数标点，并删除 `million/billion/dollars/nominal` 等单位词，再与 gold exact match；hard 是 EM，soft 是 token F1。[OfficeQA evaluator](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/envs/officeqa/evaluator.py#L8-L46)；[hard/soft 映射](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/envs/officeqa/rollout.py#L694-L710)

### 2.4 DocVQA

模型接收文档图片和问题。soft 使用 ANLS：对预测与多个 gold 计算归一化 Levenshtein 相似度，编辑距离比例达到 0.5 时记 0，否则记 `1 - normalized_distance`，并取多个 gold 的最大值。实现随后只在 `ANLS >= 0.999` 时把 hard 记为 1，所以论文式 hard accuracy 基本要求规范化文本完全一致；拼写接近只体现在 soft 诊断中。[DocVQA ANLS evaluator](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/envs/docvqa/evaluator.py#L8-L50)；[答案抽取与多 gold 评分](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/envs/docvqa/evaluator.py#L93-L113)；[hard/soft 映射](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/envs/docvqa/rollout.py#L239-L243)

### 2.5 LiveMathematicianBench

这是数学 MCQ。scorer 优先读取 `<answer>` 内的选项 label；也允许完整选项文字或答案首 token 映射回 label。最终只比较预测 label 与正确 label，hard、F1 和 substring 指标在该环境中都是相同的 0/1。[LiveMath evaluator](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/envs/livemathematicianbench/evaluator.py#L7-L62)

论文使用的四个月度数据文件来自 2025-11 至 2026-02；官方默认配置会 shuffle choices，且不向模型提供 theorem/sketch 字段。[官方数据说明](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/data/README.md#L107-L126)；[LiveMath 配置](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/configs/livemathematicianbench/default.yaml)

### 2.6 ALFWorld

模型在 TextWorld 环境中持续选择动作。每一步记录 action、reasoning、environment feedback、reward 和 done；episode 结束时直接读取环境返回的 `infos[i]["won"]`。won 为真时 hard=soft=1，否则为 0；达到 50 步仍未完成也是失败。[ALFWorld rollout/scorer](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/envs/alfworld/rollout.py#L272-L323)

## 3. 数据如何划分，验证集怎样工作

### 3.1 三份数据的职责

- `train`：目标模型带当前 Skill 执行，生成带分数的成功/失败轨迹；优化器可以看到这些轨迹。
- `selection`：每次产生 candidate Skill 后完整重跑，用于 accept/reject 和保存 `best_skill.md`。
- `test`：训练期间锁定，只在最终报告时运行 selection-best Skill。

官方 CLI 中对应名称分别是 `train`、`valid_seen`、`valid_unseen`。[官方 checkpoint 评估说明](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/ckpt/README.md#L33-L56)

所有数据型 benchmark 使用同一固定 `split_seed=42`，主结果在不相交 test split 上报告。论文附录称未另行指定时默认比例为 `2:1:7`，官方发布 manifest 也基本遵循这个比例。[论文实验设置](https://arxiv.org/pdf/2605.23904#page=8)；[论文 Appendix C](https://arxiv.org/pdf/2605.23904#page=20)；[官方 manifest](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/data/README.md#L27-L38)

### 3.2 gate 到底比较什么

每次 selection rollout 后，对所有 item 的 `hard` 取算术平均：

```text
selection_score(skill) = sum(item.hard) / number_of_items
```

论文式 gate 的规则是：

```text
if candidate_score > current_score:
    接受 candidate
    如果还 > best_score，则更新 best_skill.md
else:
    拒绝（等分也拒绝）
```

官方实现默认 gate metric 为 `hard`，且代码确实只在 `>` 时接受。[平均分实现](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/utils/scoring.py#L7-L23)；[gate 决策](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/evaluation/gate.py#L135-L225)；[论文 §3.5](https://arxiv.org/pdf/2605.23904#page=6)

当前仓库后来增加了 soft/mixed gate，但这不是论文主结果所描述的默认口径。复现论文时应使用 hard、严格大于和 paper-aligned slow-update 语义。

## 4. 候选 Skill 怎样自动产生

默认一轮训练按以下方式运行：

1. 当前 Skill 在 train batch 上执行，保存任务元数据、messages、tool calls、observations、命令输出、最终答案和 verifier feedback。
2. 按 hard score 分成成功/失败轨迹，再各自切成 reflection minibatch。
3. GPT optimizer 从失败中提出纠错规则，从成功中提出应保留规则；输出结构化 `add/delete/replace` patch。
4. 先分别合并成功/失败 patch，再去重、解冲突并排序。
5. 按文本学习率 `L_t` 只应用排名靠前的有限条编辑，形成 candidate Skill。
6. candidate 在完整 selection 上重跑，严格提升才接收。
7. 被拒编辑及其造成的分数下降保留在当前 epoch 的 rejected buffer，供后续 reflection 避免重复犯错。
8. epoch 结束时用前后两个技能在同一批 train item 上做纵向比较，产生 slow/meta guidance；最终只部署 selection-best Skill。

这使“自动迭代”成为一个真正的 propose → execute → score → gate 循环，而不是让 optimizer 自己评价自己的文案。[论文 §3.2–§3.6](https://arxiv.org/pdf/2605.23904#page=5)

论文默认优化参数为：4 epochs、rollout batch 40、reflection minibatch 8、16 个 analyst worker、merge batch 8、每 minibatch 最多 3 次 refinement、文本学习率 4、cosine 衰减到最小 2、每 epoch 20 个 slow-update 配对样本、patch 模式、target 与 optimizer 都用 medium reasoning effort。LiveMath 与 ALFWorld 因数据池和环境不同使用专用 batch 设置。[论文实验设置](https://arxiv.org/pdf/2605.23904#page=8)；[官方基础配置](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/configs/_base_/default.yaml#L59-L92)

## 5. 比较了哪些 baseline

论文列出七种对照：

| Baseline | 定义 |
|---|---|
| No skill | 冻结 target model，只使用 benchmark 默认 system prompt |
| Human skill | 每个 benchmark 由专家手写一份技能 |
| One-shot LLM skill | GPT-5.5 根据高级任务描述一次性生成，之后不更新 |
| Trace2Skill | 从 train trajectories 一次性蒸馏技能，不使用 SkillOpt 的迭代验证门 |
| TextGrad | 用自然语言“梯度”优化 prompt；用于 direct-chat 对比 |
| GEPA | Pareto reflective prompt evolution；用于 direct-chat 对比 |
| EvoSkill | 通过失败分析进化 skill folder；在存在匹配完成运行的 harness cell 中比较 |

论文对齐了每个 cell 的 target model、held-out test split 和 scorer；未在最终协议下实际测量的条目用 `–`，不混入不兼容结果。[论文 baseline 协议](https://arxiv.org/pdf/2605.23904#page=9)；[论文 Appendix C](https://arxiv.org/pdf/2605.23904#page=20)

论文没有说明这些方法使用相同的训练 token、optimizer 调用数或墙钟预算。因此它较可靠地比较了“最终效果”，但并未建立“单位离线训练成本公平”的结论。

## 6. 模型和 harness 配置

### 6.1 Target models

direct chat 共测七个目标模型：

- GPT-5.5
- GPT-5.4
- GPT-5.4-mini
- GPT-5.4-nano
- GPT-5.2
- Qwen3.5-4B
- Qwen3.6-35B-A3B

Codex 与 Claude Code 两种 agentic harness 只报告 GPT-5.5；每种 harness 测五个 benchmark，因 ALFWorld 需要持久具身环境，所以没有对应 cell。于是主结果共 `7 × 6 + 2 × 5 = 52` 个 cell。[论文表 1 与 §4.1](https://arxiv.org/pdf/2605.23904#page=7)

### 6.2 Optimizer model

论文的强 optimizer regime 使用 GPT-5.5；默认官方配置也是 GPT-5.5 target/GPT-5.5 optimizer。组件消融明确使用 GPT-5.5 同时作为 target 和 optimizer。论文另做 target-matched optimizer 实验，让 optimizer 与较小 target 同型号，并保持 rollout、gate、edit budget、buffer、slow/meta 设置一致。[官方 model 默认配置](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/configs/_base_/default.yaml#L4-L25)；[论文表 5](https://arxiv.org/pdf/2605.23904#page=13)

### 6.3 三种执行模式

- Direct chat：一次 chat-completion，Skill 前置到 system/developer instruction。
- Codex：通过 Codex CLI 在 `workspace-write` sandbox 运行，每个任务写入 `SKILL.md`；optimizer 会看到压缩后的 `codex_trace_summary.txt`。
- Claude Code：通过 Claude CLI 使用相同 workspace 契约。

三者消费相同 `best_skill.md` 格式，因此可以做跨 harness 迁移。[论文 harness 协议](https://arxiv.org/pdf/2605.23904#page=9)

论文说明 target/optimizer 默认 medium reasoning，但没有报告 temperature、模型服务快照或采样 seed。当前官方基础配置对 OpenAI 路径也没有显式固定 temperature。因此“split 可复现”不等于“LLM rollout 完全确定”。

## 7. 重复次数和统计报告

这里是论文评测最需要谨慎理解的部分：

- 明确固定的是数据 split seed 42；
- 主表、超参数表和消融表都报告单个百分比点估计；
- 论文没有报告每个设置的独立重复次数；
- 没有多随机种子均值、标准差、置信区间或显著性检验；
- Figure 3 展示的是同一训练过程在 epoch checkpoint 上的 train/selection/test 趋势，不是多次独立实验的误差带。

论文反复使用 “best measured” 的措辞是准确的：`52/52` 表示在作者实际测得的 52 个 cell 中最佳或并列最佳，不代表每个差值都经过统计显著性检验。[论文表 1 caption 与 §4.1](https://arxiv.org/pdf/2605.23904#page=7)；[论文 Figure 3](https://arxiv.org/pdf/2605.23904#page=12)

这也意味着很接近的结果需要保守解读。例如 87.3 与 87.2 的差距小于一个百分点，论文没有提供足够统计信息判断其是否超出模型随机波动。

## 8. 主要结果

### 8.1 GPT-5.5 direct chat

| Benchmark | No skill | SkillOpt | 绝对提升 |
|---|---:|---:|---:|
| SearchQA | 77.7 | 87.3 | +9.6 |
| SpreadsheetBench | 41.8 | 80.7 | +38.9 |
| OfficeQA | 33.1 | 72.1 | +39.0 |
| DocVQA | 78.8 | 91.2 | +12.4 |
| LiveMathematicianBench | 37.6 | 66.9 | +29.3 |
| ALFWorld | 83.6 | 95.5 | +11.9 |
| 六项平均 | 58.8 | 82.3 | +23.5 |

在这六个 cell 上逐项挑选最强竞争 baseline 所组成的 oracle 平均为 76.9，SkillOpt 仍高 5.4 个百分点。[论文表 1 与 §4.1](https://arxiv.org/pdf/2605.23904#page=7)

### 8.2 全体模型与 harness

- 52/52 个测量 cell 中，SkillOpt 最佳或并列最佳；
- 七个 direct-chat target model 的六 benchmark 平均绝对提升约 +17.6 点；
- GPT-5.5 在 Codex harness 上相对 no-skill 平均 +24.8 点，相对 EvoSkill +14.0；
- GPT-5.5 在 Claude Code 上相对 no-skill 平均 +19.1 点，相对 EvoSkill +3.2。

[论文 §4.1 汇总](https://arxiv.org/pdf/2605.23904#page=10)

### 8.3 迁移结果

- GPT-5.4 上训练的 Spreadsheet/LiveMath 技能迁移到 mini、nano target 后，四个 cell 均高于 no-skill，提升约 +3.0 至 +9.4；
- Codex 训练的 SpreadsheetBench 技能转到 Claude Code，较目标 no-skill +59.7；反向迁移 +43.6；
- OlympiadBench 技能不再优化，直接转到 Omni-MATH，在 GPT-5.4/mini/nano 上分别 +3.7/+1.8/+1.3。

[论文表 4](https://arxiv.org/pdf/2605.23904#page=9)

### 8.4 成本与产物大小

GPT-5.5/GPT-5.5 六个代表性训练的最终 Skill 为 379–1,995 token，只有 1–4 次 candidate update 被接受；但单 benchmark 训练消耗约 20.8M–213.8M token。论文报告的训练成本如下：[论文表 6](https://arxiv.org/pdf/2605.23904#page=14)

| Benchmark | 最终 Skill token | 接受更新数 | 训练 token |
|---|---:|---:|---:|
| SearchQA | 857 | 4 | 213.8M |
| SpreadsheetBench | 1,995 | 4 | 21.4M |
| OfficeQA | 883 | 1 | 20.8M |
| DocVQA | 959 | 3 | 188.2M |
| LiveMath | 379 | 1 | 23.2M |
| ALFWorld | 1,321 | 2 | 59.3M |

这支持的是“离线大量试错、在线复用一个小文本”的经济模型，不是低成本在线自学习。

## 9. 消融实验具体测了什么

消融只在 SearchQA、SpreadsheetBench、LiveMath 上进行，并使用 GPT-5.5 作为 target 和 optimizer。表 2 一次只改一个超参数：

- train evidence：1 example、20%、40%、80%、100%；
- reflection minibatch：1、2、4、8、16、32；
- rollout batch：8、24、40、56、full epoch；
- edit budget：1、2、4、8、16；
- scheduler：constant、cosine、linear；
- slow-update samples：5、10、20、40。

结果表明 batch/minibatch 在较宽区间内不敏感，训练证据增加通常帮助程序性任务；bounded edit budget 的多种值都可工作，constant 甚至在部分 cell 高于 cosine，因此论文支持的是“有限步长”，不是某个唯一最优 scheduler。[论文表 2 与 §4.2](https://arxiv.org/pdf/2605.23904#page=8)

核心组件消融：

| 设置 | SearchQA | Spreadsheet | LiveMath |
|---|---:|---:|---:|
| `lr=4` bounded edit | 87.1 | 77.5 | 61.3 |
| 无 edit budget | 84.6 | 75.7 | 57.3 |
| 有 rejected buffer | 87.1 | 77.5 | 61.3 |
| 无 rejected buffer | 85.5 | 72.9 | 58.9 |
| meta + slow update | 87.1 | 77.5 | 61.3 |
| 无 meta | 85.1 | 75.7 | 58.1 |
| meta 与 slow update 都无 | 86.3 | 55.0 | 59.7 |

最大降幅出现在 SpreadsheetBench 去除 meta+slow：77.5 → 55.0。由于这些仍是无误差条的点估计，宜把大幅回退视为强证据，把一两个百分点的变化视为方向性证据。[论文表 3](https://arxiv.org/pdf/2605.23904#page=8)

optimizer-strength 消融还显示，target-matched optimizer 可保留强 GPT-5.5 optimizer 增益的约 56%–74%，但四个测试 cell 都不如强 optimizer。[论文表 5](https://arxiv.org/pdf/2605.23904#page=13)

## 10. 局限与复现时的口径冲突

### 10.1 论文承认的局限

1. 依赖 scored trajectories 和可靠 selection evaluator；开放式主观任务需要人类或 model judge。
2. 虽然部署物很小，训练需要额外 rollout 和 optimizer 调用，一次性任务未必划算。
3. 只优化单域单技能，不解决大型、异构 skill library。
4. Skill 会吸收训练分布启发式，迁移到不同模型、harness 或任务时必须重新做 held-out evaluation。

[论文 Limitations](https://arxiv.org/pdf/2605.23904#page=20)

### 10.2 selection 会被反复查询

test 保持锁定是正确的，但同一个 selection split 会在大量 candidate 上反复使用，因此存在 adaptive overfitting。严格 gate 只能保证 selection hard score 单调不降，不能保证真实分布单调不降。Figure 3 表明其选择通常能跟踪 test，但没有从统计上消除该风险。[论文 Figure 3 与 gate 说明](https://arxiv.org/pdf/2605.23904#page=12)

### 10.3 论文内部有 split 文字冲突

- 表 2 caption 明确说 train-size ablation 固定使用 `4:1:5`；
- Appendix C 的 ablation protocol 又写成固定 `2:1:7`；
- Appendix C 的全局默认也是 `2:1:7`。

论文没有消解这处矛盾。官方发布的固定 manifest 应作为复现实验的更明确依据，而不要自行重建 Table 2 split。[论文表 2 caption](https://arxiv.org/pdf/2605.23904#page=8)；[论文 Appendix C](https://arxiv.org/pdf/2605.23904#page=20)

论文正文另写 ALFWorld 有“39 training、140 selection、134 test”，而官方 paper split manifest 是 39/18/134；这很可能是文字或排版错误，但仅凭一手资料不能判断 140 的来源，复现时应明确声明采用哪一份。[论文实验设置](https://arxiv.org/pdf/2605.23904#page=8)；[官方 manifest](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/data/README.md#L31-L38)

### 10.4 当前 `main` 默认不完全等于论文

paper-aligned checkpoint 使用：

```yaml
optimizer:
  slow_update_gate_with_selection: true
```

当前 `main` 默认却是 `false`，这是投稿后的 force-accept slow-update 行为，可能训练出不同 `best_skill.md`。官方 checkpoint README 明确提示了这点。[paper-aligned 复现说明](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/ckpt/README.md#L72-L87)

### 10.5 官方 release 仍不是完整的一键复现包

仓库发布了六套固定 ID/path manifest 和六份 GPT-5.5 Skill checkpoint，但除 ALFWorld path manifest 外，大多不含完整问题、答案、图片、文档或工作簿；需要从上游数据源 materialize。当前 checkpoint 也只是论文 Table 1 的一个子集，并非 52 个 cell 的全部训练状态与运行日志。[官方数据说明](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/data/README.md#L40-L53)；[官方 checkpoint 说明](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/ckpt/README.md#L1-L16)

### 10.6 Appendix 出现 SealQA，但 headline suite 没有

Appendix C 的文字列举 benchmark 时出现 SealQA，但摘要、主实验设置、表 1、官方内置环境与发布 manifest 都只包含 SearchQA、SpreadsheetBench、OfficeQA、DocVQA、LiveMath 和 ALFWorld 六项。没有 SealQA 的主结果 cell，因此不应把它计作论文已经报告的第七个主 benchmark。[论文 Appendix C](https://arxiv.org/pdf/2605.23904#page=20)；[官方六个 split](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/data/README.md#L27-L38)

## 11. 对“论文具体如何评测”的准确概括

可以把整套协议压缩成下面的伪代码：

```text
current = initial_skill
best = initial_skill
current_sel = mean_hard(run(selection, current))

for epoch in 1..4:
    for train_batch in train:
        trajectories = run(train_batch, current)
        edits = optimizer.reflect_merge_rank(trajectories, max_edits=L_t)
        candidate = patch(current, edits)
        candidate_sel = mean_hard(run(selection, candidate))

        if candidate_sel > current_sel:
            current = candidate
            current_sel = candidate_sel
            if candidate_sel > best_sel:
                best = candidate
        else:
            rejected_buffer.add(edits, candidate_sel - current_sel)

report mean_hard(run(test, best))
```

它真正验证的是：**一份自然语言程序，是否能让固定模型在一组有程序化判定的未知任务上取得更高任务成功率。** 它没有单独给“工具选择合理性”“过程安全性”“回答风格”等维度打分；这些只有在影响 benchmark 最终 hard result 时才被间接奖励。因此将这套方法迁移到推荐 Agent 时，需要自己补充约束违例、安全、证据一致性和工具策略等 verifier，不能直接把一个 LLM 总分当作论文协议的等价替代。

## 主要一手资料

- [论文摘要页与版本记录](https://arxiv.org/abs/2605.23904)
- [论文 PDF v2](https://arxiv.org/pdf/2605.23904)
- [Microsoft SkillOpt 官方仓库](https://github.com/microsoft/SkillOpt)
- [官方 paper split manifest 说明](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/data/README.md)
- [官方 paper-aligned checkpoint 说明](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/ckpt/README.md)
- [官方评分聚合实现](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/utils/scoring.py)
- [官方 validation gate 实现](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/skillopt/evaluation/gate.py)
- [官方基础配置](https://github.com/microsoft/SkillOpt/blob/b860a5cf88ce75e2bd02ca981ac21fb28cffba83/configs/_base_/default.yaml)
