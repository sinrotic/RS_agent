# 推荐 Agent 的隔离 Skill 评测

当前版本为顾客视角的 [v4](v4/README.md)：从购物目的、顾客已经提供的信息和关键缺口设计 Session，再评价澄清与推荐。它保留真实商品和画像绑定，但不把历史频次当作顾客明确要求。任务人工审核和公式校准尚未完成，可开始基线诊断，不能直接用于自动晋升。

## 当前顾客任务集 v4

[v4/benchmark.json](v4/benchmark.json) 包含 900 件商品、150 个真实画像用户、1871 个任务、2529 个 Turn，训练、开发、保留测试分别为 90、30、30 个独立用户。覆盖 14 类场景，包括预算澄清、送礼需求、替家人购物、确认过去偏好、复购、设备兼容信息不足、保修证据未知及工具故障。

顾客后续回答不预先交给 Agent：隐藏脚本根据实际回答逐轮释放，关键澄清不通过就停止。未经顾客确认的历史匹配仅单独报告，不进入主分；顾客明确说继续优先过去店铺时，才作为当前明确偏好参与排序。完整设计、限制和运行步骤见 [v4/README.md](v4/README.md)，人工材料见 [v4/calibration/blind-review.md](v4/calibration/blind-review.md)。

## 历史规则任务集 v3

[v3/benchmark.json](v3/benchmark.json) 包含 900 件商品、150 个真实数据集 Profile User、1200 个任务、1650 个 Turn。每名用户一个任务族，训练、开发、保留测试分别有 90、30、30 个独立用户，对应 720、240、240 个任务。同一用户及其需求变体不跨集合，绑定目标商品不在不同任务族重复；普通候选可以共用，不代表商品级冷启动泛化。

| 任务类型 | 数量 | 验证目标 |
| --- | ---: | --- |
| 结合画像推荐 | 150 | 使用过去类目和店铺偏好 |
| 显式要求覆盖画像 | 150 | 当前要求优先于历史偏好 |
| 修改预算 | 150 | 更新预算并保留其他条件 |
| 排除前次结果 | 150 | 排除本次实际推荐，而非预写答案 |
| 无匹配商品 | 150 | 说明无解，不用超预算商品凑数 |
| 必须属性未知 | 150 | 区分证据不足与确定无解 |
| 召回工具不可用 | 150 | 语义召回失败时利用其他可用工具 |
| 切换需求类目 | 150 | 更新类目和预算，保留数量与历史排除 |

### 热度统计与真实绑定

v3 不再用 v2 的小交互子集估算热度，而是流式扫描 `amazon_2023_recall_recent_2y_1m_3m_remote_restore` 的全部 11538991 条训练交互，覆盖 6826801 名用户和 864288 件商品。频次只由过去训练交互重新统计，忽略源记录中可能含未来信息的预计算次数；画像截止时间为 `1684108809399`，后续目标正向交互不进入画像。

为避免稀疏对象的分位点仍然只有一次交互，先限定具有至少 5 条过去正向交互的用户、至少 5 次过去交互的商品，再分别取该合格群体的第 60–90 百分位。用户合格群体为 201533 人，阈值为过去交互 8–16 次；商品合格群体为 272953 件，阈值为 16–67 次。正向指评分至少为 4；用户活跃度仍按全部过去交互计数。阈值包含两端并保留并列项，范围仅代表这份来源数据中的有足够证据对象，不是全站热度，也不恰好覆盖 30%。

随后筛选用户和商品均在热度范围内的真实后续正向交互，排除用户过去见过的目标，并回填完整扫描的商品元数据。最终合格池有 178 名用户、217 条目标交互和 66865 件有价商品；独占目标的固定种子选择最多支持 170 个任务族，当前保留 150 个，不通过放宽热度或虚构绑定凑足 200 个。目标和有偏好差异的对照商品优先进入目录，其余从合格商品池按 `seed=42` 补足。

所有入选任务族都存在画像偏好不同的候选。每名用户可回填商品事实的正向历史至少 4 条，并不等于源数据里的全部正向历史都有元数据。需求类目参考后续真实交互，表达仍为合成，不能当作该用户真实购物意图。目标只作为构建证据，不是唯一正确答案，也不传给 Agent。元数据是冻结回顾快照，不声称价格或库存属于交互发生时刻；价格使用 `SOURCE_UNIT`，不做货币推断或换算。

### v3 匹配分与目录自检

偏好仍按过去正向频次归一化，`P_category(c) = n_category(c) / max(n_category)`，店铺同理。满足所有硬条件后，效用为 `U = 0.35 × P_category + 0.35 × P_store + 0.30 × (1 − price / (1.1 × budget))`，价格项截断到 `[0,1]`。没有店铺历史时类目权重为 0.70；明确忽略画像时只评分价格。预算本身仍是硬上限，1.1 只控制软价格标尺，不允许超预算。

软价格零点放在 1.1 倍预算，避免新类目中唯一可行商品恰好位于预算上限、又没有已知偏好时整个理想排序效用为零。公式与权重明确写入合成用户表达，属于待校准的验收规则，不是已证实的真人偏好模型。需要更自然的需求时，应建立新版本并重新校准，而不是把这份表达包装成真实用户请求。

[v3/audit.json](v3/audit.json) 检查了完整目录参考路径：1350 个推荐 Turn、150 个无匹配 Turn、150 个信息不足 Turn，没有参考路径失败，也没有推荐 Turn 的零 IDCG。只按价格排序的公式对照在 772 个推荐 Turn 非最优，平均排序分约 80.50。这只说明公式可以区分这些对照，绝不是真实 Agent 成绩或线上效果证明。多轮排除自检沿参考结果执行；真正运行时必须沿该次 Agent 实际结果执行。

### 独立人工校准

[v3/calibration/blind-review.md](v3/calibration/blind-review.md) 提供 60 对结果，全部来自开发集，覆盖 30 个用户。审核者只看用户表达、过去画像和 A/B 商品事实，不看 `scoring-key.json` 的公式答案，填写 [v3/calibration/labels.json](v3/calibration/labels.json) 的偏好、审核人、理由及需求是否合理。A/B 是确定性公式参考与对照，不是真实 Agent 输出；排除前次结果任务只校准首轮，工具故障任务这里只校准推荐匹配，不验证故障处理过程。

校准检查要求至少 30 对有效人工判断、10 个独立用户、一致率至少 0.80、按用户任务族 bootstrap 的 95% 区间下界至少 0.60，且没有待修正的不合理任务。这些是初始工程门槛，不保证业务有效性，60 对也不代表穷尽所有场景。真人身份靠审核流程而非一个 `human` 字段证明；公式键分文件保存也不构成权限隔离，应由独立审核者保管。

当前标签全部空白，[v3/calibration/pending-report.json](v3/calibration/pending-report.json) 为未通过。不得使用公式、模型输出或翻转状态伪造人审。先完成任务事实和表达审核、冻结新版数据，再生成校准材料并独立标注。若随后修改任务、画像、目录或审核元数据，完整数据指纹改变，旧校准收据立即失效；必须重新生成相符材料，不能拼接旧标签。

## 历史画像任务集 v2

[v2/benchmark.json](v2/benchmark.json) 保留原始版本：300 件商品、20 个数据集 Profile User、80 个任务、120 个 Turn。每名用户一个任务族，按用户分为训练 12 族、开发 4 族、保留测试 4 族，对应 48、16、16 个任务。它用于历史工程对照，不作为当前自动晋升依据。

每个用户包含结合画像推荐、显式要求覆盖历史偏好、修改预算、排除本次实际推荐结果四类任务。需求类目来自用户后续真实正向评价过的商品，并结合过去最常见的类目构成允许范围；这仍是合成表达，不声称还原了该用户当时的真实购物诉求。目标交互只用于构建与审核，不作为唯一正确商品，也不发送给 Agent。

抽样遵循以下规则：

1. 使用 `canonical_interactions.train.jsonl` 的全部 15928 条过去交互计算用户活跃度和商品热度，不使用记录中由全量交互预计算的频次字段。历史严格早于目标文件的最早时间戳 `1630772431196`，画像只取此前评分至少为 4 的正向历史，并排除已经评价过的商品。
2. 用户和商品分别取交互数的第 60–90 百分位。分位点使用排序后 `floor((N−1)q)` 的经验值，频次阈值包含两端并保留并列项。本子集的用户阈值是 3–13 次，商品阈值是 1–2 次；并列项会扩大实际入选比例，不能把它解释为恰好 30% 的对象，更不能称为全站热门。
3. 目标从 valid/test 中筛选评分至少为 4、用户与商品都落在阈值内、目标不在该用户过去历史中的真实交互。还要求至少两条可回填商品事实的正向历史，并剔除候选偏好分完全相同、无法区分画像作用的两条交互。完成筛选后有 70 名合格用户、87 条目标交互和 7058 件合格有价商品。
4. 固定 `seed=42`，先打乱合格用户，再打乱各用户的合格目标，选择未被其他任务族占用的目标；不是独立随机配一个用户。目录保留目标及有偏好差异的对照商品，再从全部合格商品池随机补足。商品元数据两个文件均流式完整扫描，记录全文件哈希，不以文件前缀作为抽样池。

这份交互源本身是较小的既有抽样子集；以上范围和热度结论仅在该子集成立。商品事实采用冻结元数据，预算测试不声称使用目标交互发生时的价格或库存。当前全体任务仍为 `pending`，不能用于自动晋升。

### v2 个性化匹配分

历史偏好按各维度的正向频次归一化：`P_category(c) = n_category(c) / max(n_category)`，`P_store(s) = n_store(s) / max(n_store)`。仅使用可回填元数据的过去交互，未见偏好记 0；历史可回填数量另行记录，不伪造完整覆盖。

满足类目范围、原始币种、预算及历史排除等硬约束后，商品效用为 `U = 0.35 × P_category + 0.35 × P_store + 0.30 × (1 − price / budget)`，价格项截断到 `[0,1]`。没有店铺历史时，类目权重改为 0.70；明确要求忽略画像的任务只评分价格。最终仍通过下述全目录 NDCG 和完整列表门控评分，画像匹配并不替代事实核验。

上述权重是初始验收规则，明确写入合成用户表达和任务标注，并非从真人满意度学出的权重；投入真实业务前需要校准和人工审核。

全部 20 个任务族都有不同历史偏好匹配度的候选。只按价格排序的公式对照在 15 个任务族不是最优，20 族首轮平均分约 74.50；这是评测区分能力的检查，不是真实 Agent 成绩，更不是线上提升证据。

## 早期工程种子集

[v1/benchmark.json](v1/benchmark.json) 包含 200 件商品、40 个任务、55 个 Turn，分为 10 个任务族。同一类目的需求变体属于同一任务族；训练集 24 个任务、开发集 8 个、保留测试集 8 个，任务族不跨集合。

| 任务类型 | 数量 | 验证目标 |
| --- | ---: | --- |
| 明确需求 | 10 | 类目、数量、预算与排序 |
| 软偏好 | 10 | 价格和店铺偏好的权衡 |
| 修改预算 | 10 | 保留其他要求，更新预算 |
| 排除前次结果 | 5 | 依据该次实际回答排除已推荐商品 |
| 没有匹配 | 3 | 不推荐已知超预算商品 |
| 属性未知 | 2 | 不把未知保修信息说成确定满足或确定无解 |

来源是仓库已有 Amazon Reviews 2023 的商品元数据，不读取用户评论、行为或个人身份。首版在 Electronics 文件前 444 条记录中选取了 200 条有有效价格、标题和类目路径的记录，未采样到第二个输入文件。源数据分类可能不准确；价格是历史快照，不是实时价格；前缀抽样不代表整体商品分布。

原始价格没有可靠货币字段，默认使用 `SOURCE_UNIT`，不解释成美元或人民币，不进行汇率换算。只有确认来源币种后，才在新版本里显式设置 `--currency`。商品来源行号、已扫描前缀哈希、目录哈希和生成参数保存在数据中。

## 评分规则

硬约束分别返回满足、违反或未知。商品只有在所有硬约束都得到证明时才具有正相关性；软偏好按标注权重计算 0 到 1 的效用，缺失属性记零但不移除其权重，另记录事实覆盖率。

排序质量使用线性相关性增益的 NDCG，理想排序从完整冻结目录计算，不从 Agent 的召回候选计算。数量由用户表达和当前目录可行商品数量决定，不能靠重复商品凑数。所有返回商品都检查，超出前 K 的违规商品也会导致失败。

推荐 Turn 的分数为 `100 × G × NDCG`。门控 G 检查执行完成、当前需求、数量、不同商品、目录事实和工具来源。整个多轮任务只有所有 Turn 都通过才算成功；有任一失败，整个任务的门控排序分记零，保留逐 Turn 诊断分供定位问题。

如果目录中每件商品都有已知违规项，期望结果是 `no_match`；如果存在没有已知违规、但缺少证明的商品，期望是 `uncertain_match`。不足数量、无匹配和信息不足都需要明确的限制说明。IDCG 为零时排名分不适用，不伪造满分；这类任务仍进入总体成功率分母。超时、协议错误、工具失败和未完成结果不会被丢弃。

评分依据是商品事实，不是指定商品标题的相似度，也不接受 Agent 自报价格、属性或分数。所有符合需求的替代商品都可得分。

## 隔离环境

每个任务及重复试验创建新的 Java 进程、内存 Runtime、Session 和 loopback 工具环境，同一 Session 的多个 Turn 共用已发生的会话历史。v2 和 v3 的 Profile User 标识固定绑定到真实数据集用户，并从同一份只读画像快照开始，不再随机生成画像 ID。v1 的匿名工程种子仍使用临时画像标识。候选 Skill 只通过内存 overlay 加载，不修改原文件、生产 Runtime 或生产数据库。

工具依据真实调用参数返回结果，支持当前目录的类目、价格、商品 ID、详情、目录事实证据和只读偏好快照。v2 和 v3 的画像进入 Java 模型上下文和 `session_memory`；推荐工具按画像类目和店铺偏好、词面匹配、价格顺序排序，排除过去已经评价过的商品，并拒绝工具参数改绑其他用户。`recommend_cold_fallback` 不用画像加分；`constraints.ignore_profile_preferences=true` 可在隔离环境显式关闭画像加分，但仍排除过去评价过的商品。该实现不是生产向量召回、训练排序模型或完整业务服务集成。业务工具预算默认每 Turn 16 次，Java profile 默认最多 8 次循环，进程任务超时默认 180 秒，单次模型 HTTP 超时 60 秒，Java 最大堆为 1GB。

运行报告记录真实画像标识和快照哈希，正式 Java 实验还核验画像实际注入证明。加载时检查画像哈希、历史时间、交互归属、目标正向证据和用户级集合隔离；候选版本之间的数据指纹包含完整画像，不能悄悄改画像后仍称为同条件比较。

种子集包含一组 RAG 不可用配置；预算耗尽、环境重置及查询过滤另有工程验收测试。RAG 只返回商品目录事实，不生成评论证据；未实现的专用工具会明确失败。没有购买、支付、生产偏好写入或任意 shell 工具。

模型使用真实 `RsAgentLoop` 的外部模型 Interface，运输实现为评测专用的 `benchmark-openai-json/1`，不是生产 `SpringAiAgentModelStreamClient`。工具 schema 的无序字段同时规范化后发送和计算哈希，避免跨 JVM 顺序变化影响重复实验。

目前输出投影支持商品 ID、已渲染 card set 和含 ID 的比较块。A2UI、纯文本商品列表、无法解析的 card set 或纯文本比较表会标记为不支持，不能静默计为成功。无匹配及限制说明使用确定性中文规则投影，不能替代语义审核；价格匹配分也不能证明推荐理由没有编造事实。正式使用前，应审核这种投影是否适合目标输出方式，补充理由事实与 UI 评价。

工具只能连接本机冻结环境；模型连接显式配置的端点。这不是操作系统级网络沙箱，也不能证明远端模型权重始终不变。正式比较应固定模型服务的版本、权重、采样参数和服务配置。

## 运行命令

以下 Python 命令在 `python_agent` 目录执行。输出路径必须是新文件，已有结果不会被覆盖。本节保留 v3 规则任务的历史复现流程；当前顾客任务的构建、澄清运行和校准流程使用 [v4/README.md](v4/README.md) 中的命令，不用下列 v3 构建命令覆盖 v4。

校验已交付任务集：

```powershell
python -X utf8 scripts/evaluation/skill_benchmark.py validate --dataset benchmarks/skill_benchmark/v3/benchmark.json
```

复现当前口径时，先完整扫描训练交互计算热度，再抽取入选用户的全部过去历史。生成器校验原始全文件与快照哈希，不允许用小快照重算分位点。以下输出采用新版本路径，避免覆盖现有 v3；全量统计保留计数器，不整体加载交互和约 7GB 元数据，执行须遵守仓库内存上限：

```powershell
python -X utf8 scripts/evaluation/skill_benchmark.py prepare-population --history data/processed/amazon_2023_recall_recent_2y_1m_3m_remote_restore/canonical_interactions.train.jsonl --targets data/processed/amazon_2023_recall_recent_2y_1m_3m_remote_restore/canonical_interactions.valid.jsonl --targets data/processed/amazon_2023_recall_recent_2y_1m_3m_remote_restore/canonical_interactions.test.jsonl --min-user-positive 5 --min-item-interactions 5 --seed 42 --out-dir outputs/skill_benchmark/population-v4
python -X utf8 scripts/evaluation/skill_benchmark.py build-personalized --source data/processed/amazon_2023_base/Electronics/metadata.base.jsonl --source data/processed/amazon_2023_base/Office_Products/metadata.base.jsonl --history outputs/skill_benchmark/population-v4/history.jsonl --targets outputs/skill_benchmark/population-v4/targets.jsonl --population outputs/skill_benchmark/population-v4/population.json --seed 42 --lower-quantile 0.6 --upper-quantile 0.9 --catalog-limit 900 --family-limit 150 --out outputs/skill_benchmark/v4-core.json
python -X utf8 scripts/evaluation/skill_benchmark.py strengthen --dataset outputs/skill_benchmark/v4-core.json --out benchmarks/skill_benchmark/v4/benchmark.json
python -X utf8 scripts/evaluation/skill_benchmark.py audit --dataset benchmarks/skill_benchmark/v4/benchmark.json --out benchmarks/skill_benchmark/v4/audit.json
```

人工审核、纠正任务并冻结到新文件后，才为该冻结版本生成校准材料。下面的 `reviewed-benchmark.json` 和 `labels.completed.json` 必须由真实审核流程准备，不能只复制并改状态；输出收据绑定完整数据和当前评分器指纹：

```powershell
python -X utf8 scripts/evaluation/skill_benchmark.py calibration-pack --dataset benchmarks/skill_benchmark/v4/reviewed-benchmark.json --pairs 60 --out-dir benchmarks/skill_benchmark/v4/calibration
python -X utf8 scripts/evaluation/skill_benchmark.py calibration-check --key benchmarks/skill_benchmark/v4/calibration/scoring-key.json --labels benchmarks/skill_benchmark/v4/calibration/labels.completed.json --out benchmarks/skill_benchmark/v4/calibration/report.json
```

构建 Java 入口，在 `java_agent` 目录使用 JDK21 执行：

```powershell
mvn -pl rs-service-agent -am package -DskipTests
```

准备真实模型配置，可以复制 [model.example.json](model.example.json) 到本地文件，再替换服务地址和模型 ID。`base_url` 包含 `/v1`，密钥仅从 `RS_BENCHMARK_API_KEY` 环境变量读取，不放入配置或报告。若默认 Java 不是 JDK21，增加 `--java` 指定可执行文件路径。

```powershell
python -X utf8 scripts/evaluation/skill_benchmark.py run --dataset benchmarks/skill_benchmark/v4/reviewed-benchmark.json --calibration-report benchmarks/skill_benchmark/v4/calibration/report.json --split dev --repeats 3 --model-config local-model.json --out outputs/skill_benchmark/baseline.json
python -X utf8 scripts/evaluation/skill_benchmark.py run --dataset benchmarks/skill_benchmark/v4/reviewed-benchmark.json --calibration-report benchmarks/skill_benchmark/v4/calibration/report.json --split dev --repeats 3 --model-config local-model.json --skill-overlay candidate-overlay.json --out outputs/skill_benchmark/candidate.json
python -X utf8 scripts/evaluation/skill_benchmark.py compare --baseline outputs/skill_benchmark/baseline.json --candidate outputs/skill_benchmark/candidate.json --out outputs/skill_benchmark/comparison.json
```

`candidate-overlay.json` 是 `skill_name -> {description, content}` 的 JSON 对象，content 是候选 Skill 的完整内容。每次运行会核验实际 Runtime 中的内容哈希，不接受只贴候选版本标签而没有应用变更。

没有人审收据时可以先运行 v3 开发集作诊断，省略 `--calibration-report`，但比较会阻止晋升；错误、过期或未通过的收据不能当成通过证据。开发集比较用于调试，最终验收仍需对未被优化器反复查看的保留测试集执行同条件成对实验。

不连接真实模型的工程检查：

```powershell
python -X utf8 scripts/evaluation/skill_benchmark.py self-check --out outputs/skill_benchmark/engineering-selfcheck.json
```

这个检查仍运行真实 Java Loop，但外部模型是可控 HTTP 替身。标准示例排序得 100，反转排序得约 92.32，只证明评分、工具查询和 Skill overlay 的工程链路正确，不进入真实能力结论或晋升流程。

## 人工审核与版本冻结

当前任务的 `review_status` 全部为 `pending`，`human_reviewed` 为 false。自动生成只证明可重复构建，不能证明需求表达自然、用户偏好合理或商品分类正确。

每个任务族至少检查以下事项：

1. 类目、店铺、价格和属性能否追溯到原始元数据；单位和未知字段是否准确。
2. 用户表达是否完整承载 gold，特别是数量、软偏好权重和预算变更，是否泄漏目标商品答案。
3. 多轮更新是否只改了用户表达的要求；排除操作是否基于实际前次结果。
4. 全目录的可行商品、潜在可行商品和理想排序是否合理，是否存在无法区分优劣的零 IDCG 情况。
5. 结果投影与限制说明是否准确；相关环境故障是否具有明确的处理预期。

人工可以改写表达、纠正事实、删除不合理任务或增加真实失败场景。发布到新版本，记录审核人、日期、理由和来源，只有完成审核才将任务设为 `approved`、manifest 设为 `human_reviewed: true`。不要为了让比较报告通过而只翻转状态。事实变更需要重算 `catalog_sha256`，可使用 dataset 模块的 `fingerprint`。

v2 和 v3 还须审核用户—目标交互归属、热度统计的输入范围、截止日前的历史、画像覆盖率和合成需求是否合理。画像变更需要重算 `profiles_sha256`；修改画像、商品池、评分权重或抽样规则都必须建立新版本，不能重用旧版成绩或校准收据。v3 全目录参考路径通过不替代上述人审，也不证明推荐理由和 UI 正确。

## 后续自进化的接入方式

将 `run_benchmark` 和 `compare_runs` 作为候选 Skill 的验收 Interface。优化器读取训练或开发集的失败原因、工具轨迹和逐任务分数，生成候选 overlay；用相同商品、环境、模型配置、随机种子和重复次数重新运行，只允许 Skill 发生变化。

比较会检查数据、Python 实现、Java Runtime、评分器及校准收据指纹，按任务族进行成对 bootstrap，报告成功率与排序分变化、95% 区间和成功退化案例。候选必须没有成功退化及排序退化，并在成功率不下降的条件下至少有一项可靠提升。晋升建议还要求人工审核、真实 Java 模型实验、无执行异常、单一冻结 Runtime、保留测试集及至少 20 个独立任务族。v1 测试集只有两个任务族，v2 只有四个；v3 有 30 个，满足数量门槛但不保证统计功效。v3 同时要求对应冻结版本的独立人工评分校准通过，即使其他结果理想，缺少校准也不能晋升。

`eligible_for_promotion` 只是评测侧建议，`auto_deploy` 永远为 false。当前没有实现候选生成、自动修改 Skill、版本发布或回滚。后续还需加入多次候选搜索的统计控制、模型服务版本证明，以及测试集访问审计。

按 split 划分不等于保密：首版 JSON 中的测试 gold 在仓库可读。正式自进化应把测试 gold 放在优化器不能访问的独立评价服务或权限域，仅在候选确定后验收；不要让优化器循环查看测试失败再改进。

## 验收测试

普通评分与环境验收无需模型服务。Java 端到端验收需要已编译入口，显式设置 `RS_BENCHMARK_TEST_JAVA` 为 JDK21 的 java 路径：

```powershell
python -X utf8 -m pytest tests/test_personalized_skill_benchmark.py tests/test_skill_benchmark.py tests/test_skill_benchmark_population.py tests/test_skill_benchmark_readiness.py tests/test_evaluation.py -q
```

主要测试覆盖冻结目录 NDCG、全列表门控、未知属性、缺失软属性、来源核验、多轮门控、失败分母、任务族泄漏、工具预算、状态隔离和候选 Skill 的实际加载。画像专项覆盖固定种子复现、真实交互绑定、过去画像、频次效用、不同画像改变结果、拒绝跨用户改绑、画像哈希和用户级隔离，以及真实 Java Loop 中的画像注入和历史读取。v3 新增全量热度与小快照区分、合格群体分位点、压力场景、盲审材料与公式键分离、任务族一致性区间、未校准禁止晋升、无效收据拒绝及价格效用零点边界。生成和执行均限流进行，不加载本地大模型；测试中的合成审核标签不写入交付的人审材料。
