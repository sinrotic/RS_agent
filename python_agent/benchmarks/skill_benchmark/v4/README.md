# 顾客视角购物会话评测

v4 评价 Agent 能否根据顾客当前目的完成合理的澄清和推荐，而不要求顾客说出开发者的画像、权重或归一化规则。商品、过去画像、真实用户与目标交互绑定沿用 v3；购物情境是人工设计的合成模板，不是复原出的真人购物对话。当前可用于基线诊断，任务审核和人工评分校准仍未完成。

## 数据范围和场景

[benchmark.json](benchmark.json) 包含 900 件商品、150 个真实 Profile User、1871 个任务、2529 个 Turn。训练、开发、保留测试有 90、30、30 个独立用户，分别对应 1119、374、378 个任务。同一用户的所有变体只属于一个任务族和一个集合；58个兼容场景及13个复购场景不是新增独立用户。

| 场景 | 数量 | 评价重点 |
| --- | ---: | --- |
| 明确信息下选购 | 150 | 根据当前类目和预算选1款，不强制猜历史偏好 |
| 价格敏感但缺预算 | 150 | 问清可接受价位后推荐，不猜一个预算 |
| 送礼但缺需求 | 150 | 问收礼人需求，不把本人历史当作对方偏好 |
| 替家人购买 | 150 | 当前明确方向优先，禁用本人历史加分 |
| 明确优先便宜 | 150 | 在硬条件内按价格优先 |
| 明确店铺偏好 | 150 | 只对顾客说出的店铺优先要求评分 |
| 顾客确认过去偏好 | 150 | 过去店铺经当前顾客明确确认后成为显式偏好 |
| 改变预算 | 150 | 保留其他要求，更新预算，允许最终无匹配 |
| 不接受前次结果 | 150 | 根据实际回答排除，不用固定预写商品 |
| 保修证据缺失 | 150 | 区分商品信息未知与确定无解 |
| 召回工具不可用 | 150 | 在其他可用工具中寻找依据 |
| 预算内无商品 | 150 | 明确无匹配，不超预算凑数 |
| 设备信息不足 | 58 | 先问型号或接口；顾客仍不知道时提供核实步骤 |
| 明确复购同款 | 13 | 允许推荐买过的商品，只对同款要求作硬检查 |

用户与商品仍来自基于11538991条过去训练交互计算的合格群体第60–90百分位：用户过去交互8–16次，商品16–67次。先要求用户至少5条过去正向交互、商品至少5次过去交互，分位点只代表该有证据来源群体，不代表全站。完整统计来源和哈希保留在 manifest；画像截止后的目标交互不进入历史。场景数量增加不等于用户样本独立性增加。

预算取与目标商品价格有关的整额，表达不暴露精确目标价格。类目表述检查完整路径，区分笔记本、平板、音箱的同名支架；“Camera”在本快照对应相机电池充电器，“Speaker”对应音箱连接线，“Computer Workstations”对应电脑桌。此处纠正的是已核对的类目表达，原始分类仍需人工审核。

## 顾客信息与条件会话

一条任务分别保存购物情境、公开顾客表达、隐藏评分条件和后续顾客脚本。公开表达不再出现“画像”“35%”“归一化”“评价过”等评测术语。原始价格币种未确认，所有预算数字按冻结商店标价单位理解；单位说明属于公开商店环境，而不是让顾客说出 `SOURCE_UNIT`，也不称为人民币或美元。

价格敏感任务的会话例子：

> 顾客：想买电脑机箱，先帮我选1款，别太贵。
>
> Agent：你的预算大概是多少？
>
> 顾客：预算230以内就好。

执行器最初只拿到第一条顾客表达。评测环境根据实际公开问题检查关键字段；通过后才返回预算。没有问到预算、重复问已知信息、问过多问题或先保证某商品符合未给出的预算时，不提供后续答案，整个任务不能成功。这只要求这些明确价格敏感、事先定义预算缺口的场景澄清，不声称任何没有预算的浏览都必须先提问。

兼容任务先询问设备型号或接口，隐藏顾客回答为暂时不知道型号。此时正确行为是说明不能确认兼容、指导查看设备设置、铭牌或说明书，暂不定商品。不能虚构主板、接口、尺寸或商品规格；顾客也不能替商家补充未知保修证据。

条件会话使用隔离环境的 `/customer` 端点逐轮推进，模型不能调用这个端点作为业务工具。运行器核对环境收到的实际回答与最终报告指纹，防止先提交正确问题取得回复、再换成另一份回答。它是有限、确定性的顾客脚本，不是自由对话真人模拟器，也不是操作系统级网络隔离。

## 主分与历史偏好

主分的硬条件来自当前公开需求及商店单位：类目和完整路径、明确预算、数量、明确同款或保修条件。历史买过不自动排除；只有顾客明确拒绝前次结果才动态排除。后续预算和礼物类型只在顾客回答之后成为当前硬条件。

没有明确便宜或店铺优先要求时，符合硬条件的商品具有相同基础相关性，不用隐藏的历史频次制造一个“唯一最好”的答案。明确价格优先或店铺优先时，仅使用该显式偏好，效用为 `R = (1 + S_explicit) / 2`；无显式偏好时 `R = 1`。价格偏好为截断到 `[0,1]` 的 `1 − price / (1.1 × budget)`，店铺偏好为匹配取1、不匹配取0。基础相关性保证不匹配软偏好的可行替代商品不被当作硬违规，也避免理想排序全部为零。这仍是待人工校准的排序代理，不是顾客真实满意度。

历史偏好分三种处理：

1. 顾客未确认：类目与店铺历史匹配分别列为 `history_alignment` 诊断，不参与主分和晋升，不用固定35%权重惩罚另一款合格商品。
2. 顾客当前明确确认过去店铺：该店铺成为当前显式偏好，与顾客直接说出的店铺要求一样参与排序。不是自动把历史频次变成强偏好，也不是要求必须从该店铺购买。
3. 送礼或替别人购买：历史诊断及召回加分禁用，不把本人的长期偏好转移给对方。

隔离召回按词面、价格排序，只在并列处使用未经确认的历史参考，仍支持显式关闭历史。真实商品目录与完整路径过滤决定候选，不按隐藏答案重放商品。

推荐仍使用独立完整目录 NDCG，门控检查硬条件、数量、重复商品和实际工具来源；任一执行轮次失败或条件会话未完成，整个任务不成功。澄清和安全指导单独记录 `interaction_score`，不伪装成推荐排序分。未走到后续推荐的任务只要计划有可评分推荐，任务排序分仍为0，而不是被移出分母。澄清及指导成功率使用计划轮次作为分母，未到达的指导也不能提升报告成功率。

## 自检和人工校准

[audit.json](audit.json) 检查目录参考路径、缺失信息场景、完整类目路径及排序零分母，不证明真实 Agent 能力。Java 回归使用真实 `RsAgentLoop` 与受控 HTTP 模型，验证问题投影、隐藏顾客回复的逐轮释放、实际工具来源与会话结束。

[calibration/blind-review.md](calibration/blind-review.md) 提供120对开发集盲审材料，覆盖30名用户，包含推荐与澄清对照。A/B是确定性的参考与控制结果，不是真实模型成绩；无模型或公式生成的人审标签。审核者看公开需求、过去证据和候选，不读取单独保存的 `scoring-key.json`，填写 `labels.json` 的 A/B/tie/invalid、审核人、理由及需求是否合理。

审核重点是需求是否自然、每条主分条件是否已公开、类目翻译是否对应商品、问题是否真有必要、未知兼容与保修是否正确处理，以及历史参考是否越权。没有明确偏好的合格方案可以并列。关键字段问题和限制说明目前采用确定性中文规则投影，会漏掉同义表达，也可能误判关键词；必须审核该投影，不能宣称已经完成自由语言的语义评价。推荐理由、性能断言和完整 UI 也尚未全面评分。

通过门槛保留至少30对有效人审、10个独立用户、一致率至少0.80、用户任务族bootstrap的95%区间下界至少0.60且无待纠正任务；这是工程门槛，不保证业务有效性。全部120对目前尚未标注，[calibration/pending-report.json](calibration/pending-report.json) 未通过。题集事实和表达先审核、冻结新文件，再重新生成该冻结版本的盲审材料；当前材料可用于预审，不能在修改题集后复用旧指纹收据。评分器指纹同时包含推荐评分、顾客交互评分和gold校验。

## 构建和执行

命令在 `python_agent` 执行，输出必须是新文件。复现顾客构建不需要重新扫描大数据，来源使用已冻结的v3事实和绑定：

```powershell
python -X utf8 scripts/evaluation/skill_benchmark.py customerize --dataset benchmarks/skill_benchmark/v3/benchmark.json --out outputs/skill_benchmark/customer-rebuild.json
python -X utf8 scripts/evaluation/skill_benchmark.py validate --dataset outputs/skill_benchmark/customer-rebuild.json
python -X utf8 scripts/evaluation/skill_benchmark.py audit --dataset outputs/skill_benchmark/customer-rebuild.json --out outputs/skill_benchmark/customer-rebuild-audit.json
```

先审核并纠正任务，冻结到新版本。下面的 `reviewed-benchmark.json` 必须经过真实审核，不是只翻转状态；标注文件由独立审核者填写：

```powershell
python -X utf8 scripts/evaluation/skill_benchmark.py calibration-pack --dataset benchmarks/skill_benchmark/v5/reviewed-benchmark.json --pairs 120 --out-dir benchmarks/skill_benchmark/v5/calibration
python -X utf8 scripts/evaluation/skill_benchmark.py calibration-check --key benchmarks/skill_benchmark/v5/calibration/scoring-key.json --labels benchmarks/skill_benchmark/v5/calibration/labels.completed.json --out benchmarks/skill_benchmark/v5/calibration/report.json
```

Java入口修改后需要JDK21重新构建。在 `java_agent` 执行 `mvn -pl rs-service-agent -am package -DskipTests`。模型配置使用上级 [model.example.json](../model.example.json)，密钥只从环境变量读取。

```powershell
python -X utf8 scripts/evaluation/skill_benchmark.py run --dataset benchmarks/skill_benchmark/v5/reviewed-benchmark.json --calibration-report benchmarks/skill_benchmark/v5/calibration/report.json --split dev --repeats 3 --model-config local-model.json --out outputs/skill_benchmark/customer-baseline.json
python -X utf8 scripts/evaluation/skill_benchmark.py run --dataset benchmarks/skill_benchmark/v5/reviewed-benchmark.json --calibration-report benchmarks/skill_benchmark/v5/calibration/report.json --split dev --repeats 3 --model-config local-model.json --skill-overlay candidate-overlay.json --out outputs/skill_benchmark/customer-candidate.json
python -X utf8 scripts/evaluation/skill_benchmark.py compare --baseline outputs/skill_benchmark/customer-baseline.json --candidate outputs/skill_benchmark/customer-candidate.json --out outputs/skill_benchmark/customer-comparison.json
```

没有人审收据时可以先运行v4开发集作诊断，但比较不得建议晋升。候选确定后才在未反复用于调试的测试集同条件复测。v3与v4的任务及评分口径不同，成绩不可直接相减称为提升；只能在同一冻结版本里比较旧Skill与候选Skill。

当前不涉及真实库存、支付、配送、生产偏好写入或设备规格库。测试gold和隐藏顾客脚本仍在仓库可读；正式自进化须另行隔离优化器访问权限。评分建议不自动发布，`auto_deploy` 始终为false。

## 回归验收

设置 `RS_BENCHMARK_TEST_JAVA` 为JDK21的java可执行文件后，运行包含真实Java澄清链路的验收：

```powershell
python -X utf8 -m pytest tests/test_customer_skill_benchmark.py tests/test_personalized_skill_benchmark.py tests/test_skill_benchmark.py tests/test_skill_benchmark_population.py tests/test_skill_benchmark_readiness.py tests/test_evaluation.py -q
```

测试覆盖有针对性的澄清、已知信息不重复问、不能用自报字段伪造问题、未知型号的安全指导、历史不作隐藏要求、顾客确认偏好后的显式排序、复购、完整路径过滤、条件回复与停止、真实Java问题投影，以及旧版本公式和画像执行回归。合成测试标签不会写入交付的人审材料。
