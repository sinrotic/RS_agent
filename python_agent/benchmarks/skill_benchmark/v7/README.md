# 购物质量评测与离线 Skill 自进化

本版先固定推荐模型、工具和商品环境，只优化推荐 Skill 的指令。评测、双人独立标注、盲审校准和有界择优循环已经接通；真实质量标签仍待独立审核，评价和优化模型也未在本次工作中启用。所有候选只在隔离进程应用，没有自动上线路径。

## 任务与环境范围

`benchmark.json` 从冻结 v6 扩展，保留原 900 件商品、150 个真实画像用户及用户划分，共 2899 个任务、3661 个潜在 Turn。train/dev/test 为 1735/562/602 个任务，用户仍为 90/30/30。900 个新增任务覆盖无合格供给、价格未知、供给不足、工具持续故障、短暂故障和不可信工具文本，每类每名用户一条。

任务沿用已确认的中上热度商品和中上活跃画像。原 64 组画像对照仍只有 12 对独立用户，变体不增加独立样本数。完整覆盖见 `coverage.json`；冷启动、长尾商品、真实库存、配送、运费、优惠与付款不在本版认证范围内。供给不足是隔离目录的受控可用范围，不冒充真实库存。

工具与评分器共享同一冻结环境事实视图。价格被遮盖时仍可返回待核实商品，不能当成已满足预算，也不能误报没有供给。持续故障时评价诚实降级，不要求虚构商品凑数；短暂故障允许有限重试。商品或工具描述中的指令始终是待处理数据。

目录币种仍为原始标价单位，不称人民币或美元。场景是基于真实商品和历史画像的合成购物任务，不是复原的真人对话；过去正向评价不证明购买、年龄、职业、设备或稳定喜好。

## 独立模型生成自然请求（候选区）

原模板集保留为受控回归测试。`synthesize` 另建自然表达候选包，不覆盖 `benchmark.json`，不改变原评分器，也不把模型预审当成人工质量标签。

生成模型 A 只收到若干同类目商品事实、匿名的最多 12 条正向评价与表达覆盖目标，输出顾客原话，不输出答案或约束。旧请求、旧 gold、未来正向评价锚点及内部身份不进入模型输入。表达覆盖目标包括口语、用途困扰、信息不足、送礼、当前偏好变化、比较取舍、轻微笔误与矛盾要求；目标不是固定措辞。合成的用途和情境不冒充真实历史。

审核模型 B 用两次无共享聊天历史的调用处理：第一次只看顾客原话提取硬条件、软需求、未知项、收礼人和澄清问题；第二次才看原话、提取结果及独立商品/历史事实，预审自然性、提取忠实度、事实边界和澄清策略。B 看不到 A 的预设答案，因为 A 不产出答案。逐字引用只能证明来源存在，约束含义与遗漏仍需语义审核和人工核对。

默认要求不同的配置模型名和身份；仅换提示词不算模型隔离。不同模型名不证明后端权重不同，也不消除共享偏差；B 提取后再预审仍可能保留自身偏差，正式金标准需要独立人审和既有评分校准。现有质量裁判不接收生成模型的意图或所谓正确商品。

用户明确同意时，可增加 `--allow-shared-model-preview`，用同一个模型的三次隔离上下文调用做展示预览。产物明确记录 `model_independence=shared_model_preview`，不声称审核独立；仍为 `is_gold=false`、未人审且不自动部署，也没有自动加入正式题集的路径。该选项不绕过缺配置、证据、协议或调用预算检查，默认隔离要求保留。

种子仅来自原 train/dev 授权画像，沿用用户、family 和统计簇划分，按类目、集合与独立簇均衡选择，哈希打破并列；不重新抽取商品/用户，不使用隐藏 test 用户。每个模型只收到匿名事实子集，身份绑定与全目录检查保留在本地候选包。默认 6 个种子、每种子 2 条，最多 36 次模型调用；预算在首个调用前检查。每条处理后新建 checkpoint，故障不重试、不放行；所有文件须写入新目录。

重复/近重复表达、无原话依据的约束、预审失败、未知或模型异常都进入隔离区。程序只对已支持的条件做三值目录核对，数量、用途、续航等未支持条件保留为待核实；部分条件的可行商品数不代表完整需求已满足。无合适供给、矛盾需求和信息不足也可以是合理测试题。字符近重复检测不证明语义多样性；人工仍需检查是否都是同一种购物逻辑。

所有产物均为 `is_gold=false`，通过预审也只到 `pending_independent_human_review`。当前未提供将这些候选自动导入正式题集的路径。人工审核请求与约束、补足用途事实、另做推荐质量标签后，才能编入新的冻结评测版本并重新校准。此入口暂只合成首轮请求，真实多轮顾客行为及真实请求分布仍需另外收集和审核。

在 `python_agent` 下运行：

```powershell
python scripts/evaluation/skill_evolution.py synthesize --dataset benchmarks/skill_benchmark/v7/benchmark.json --seed-limit 6 --variants 2 --max-calls 36 --out-dir .runs/request-synthesis-001
```

分别设置 `RS_REQUEST_GEN_BASE_URL/MODEL/API_KEY` 与 `RS_REQUEST_VERIFY_BASE_URL/MODEL/API_KEY`，可用各自 `MAX_TOKENS` 限制输出预算。配置不继承推荐、裁判或优化模型的密钥。仅向已获准的数据处理端点发送匿名事实；去除内部 ID 不等于完整隐私匿名化，商品历史仍可能具有可识别性。运行前需确认提供方、处理权限和调用费用。

## 用途事实与独立质量标注

`use-evidence-review.json` 是待补录模板，不含虚构规格或测试结果。用途判断需要的重量、续航、降噪、墨水干燥、包装或兼容规格，可通过 `apply-evidence` 导入独立规格或测量证据。每项须有 HTTPS 来源、原话、核实时间与两名不同人工审核人。程序检查来源结构，审核人负责核实内容和数值；厂商声明不等于独立实测。补录另存新题集，并使旧质量标签和校准失效。

`quality-review.json` 是非测试任务的空白双审包。每位评审先独立判断任务是否合理，再为全部硬条件可行商品填写用途适合度和适用的画像适合度：0 不适合、1 勉强、2 合理、3 相对更适合，允许并列。每项保留理由和来源引用，证据不足保持未知并停止批准。

两个初审一致才合并；等级分歧须由第三位独立评审裁决，不取平均冒充真值。相同需求下两人可以合理地得到相同商品。当前要求、收礼人和会话反馈优先，相关历史仅作弱证据；不奖励不同商品 ID，也不把历史频率当成个人满意度。程序不能认证评审身份或替代独立工作流程，审核组织和记录需要实际执行。

标签包绑定整个题集与环境事实，不能删掉不喜欢的候选来提高分数。测试标签需显式 `--include-test` 单独导出，由评审与验收负责人保管，优化模型不接收这些材料。所有标签未完成前，题集不能进入正式自动择优。

标注材料展示相关类目的完整商品事实，并绑定完整环境目录哈希，减少无关商品重复。涉及“刚才那款”的任务，运行时按真实前序回答排除商品，裁判同时接收已经发生的回答，不提前释放后续顾客消息。

## 分层评分

硬条件、数量、来源和必要澄清继续使用原有可审计检查。明确违规不会被其他质量分抵消。用途和画像分别按独立人工分级计算 NDCG：`gain = 2^grade - 1`，按位置对数折扣，与冻结环境中的理想排序比较。两者分别报告，不用任意权重混成满意度。

人工标为用途不适合的商品不能用来凑推荐数量；全部可行商品都不适合时，诚实说明无合适商品可以成功。只澄清、核实指导、价格未知或正确无供给的任务，排序不适用，不当作推荐零分失败。

独立裁判模型评价澄清、事实依据、画像使用及适用的异常处理。0 明显失败、1 明显不足、2 合理完成、3 表现充分，证据不足为 null；非 null 必须引用输入中的原文。程序校验引用存在，不声称引用能证明语义判断正确。未知、裁判异常和缺少独立标签不会默认通过。

受控价格未知和供给不足场景按真实环境修正机器投影，避免要求某个中文关键词。结构标记不代表顾客已经得到解释，实际说明是否诚实、充分仍由独立语义评审与人工校准核对。

校准后，结构成功、标签完整且所有适用语义维度至少为 2，才形成 `quality_success=true`。用途或画像相关性为 0 的选中商品会失败。主报告保留分数向量、失败原因、覆盖情况；`overall_score` 和 `satisfaction` 仍为空，不能从代理评分推导真实购买满意度。

## 盲审校准

先在 train 或 dev 跑真实隔离 Agent，导出校准材料。审核包不包含裁判分数，评分键另存，不能给审核人或优化模型。两名人工独立标出适用维度等级与结构成功，分歧第三人裁决。

质量校准要求每维至少 30 个有效判断、10 个独立统计簇、精确等级一致率至少 80%，且没有把人工判定不合格的结果放行。各已出现异常场景和澄清类型至少覆盖 3 个独立簇。另须完成原有结构评分校准。阈值是工程验收口径，不保证业务效果；发现合理回答被规则误判时，应修正评分器并重新校准，不能让优化器学习迎合错误规则。

收据绑定题集、来源标签、评分器代码及裁判配置，不能只翻转 `passed`。模型别名不证明供应商后端版本稳定，应固定可用版本并重新校准变化。推荐模型、裁判模型和优化模型分别配置；独立调用不等于判断天然正确。

## 有界择优流程

`evolve` 首先检查独立标签、两类校准、真实 Java Adapter、资源预算与留出登记。门槛未满足时输出阻止原因，不调用推荐或优化模型。

通过后运行开发基线，再用训练失败生成候选。反馈只包含已核实的训练问题、受限工具事实、相关画像和独立标签理由；运行与评价器故障不作为 Skill 缺陷。优化器只能改已有 Skill 的 content，保持名称、描述、模型、工具和权限不变，不能写入商品或用户 ID。

每个候选按相同模型、种子、目录、评分器、画像可见性重复运行开发集。按独立统计簇计算配对置信区间，检查质量成功率、各质量维度和场景退步。没有可信改善、出现未知或关键退步时保留旧版；重复候选跳过，没有进展或达到预算便停止。默认 2 轮、每轮 2 个候选、3 次重复、最多 20000 个试验，依次运行，Java 子进程使用既有 1GB 堆限制。

最终候选与最初基线再比较，通过后才各跑一次冻结 test 集。共享 `holdout-registry` 原子登记已使用的冻结测试签名；同一题集跨运行不能反复消耗，失败也不自动释放登记。该登记不替代跨数据批次的画像重叠审核；新验收批次需要独立留出管理，不能通过换目录绕过登记。

留出不通过则最终版本保留最初 Skill，开发候选仅保留为诊断产物。通过也只标记 `pending_manual_release_review`，不写源 Skill、线上 Runtime 或推荐偏好。线上评价生成的改进任务现在指向同一离线入口，但真实案例仍须授权脱敏、人审 gold 和集合隔离，不能直接当成独立标签。

## 本地入口

以下命令在 `python_agent` 目录执行，所有输出使用新路径。初始 v7 的标签和证据模板尚未批准，不要把空白包改成已通过。

```powershell
python scripts/evaluation/skill_evolution.py export-skills --out .runs/baseline-skills.json
python scripts/evaluation/skill_evolution.py evidence-pack --dataset benchmarks/skill_benchmark/v7/benchmark.json --out .runs/use-evidence.json
python scripts/evaluation/skill_evolution.py apply-evidence --dataset benchmarks/skill_benchmark/v7/benchmark.json --evidence .runs/approved-use-evidence.json --out .runs/v7-with-facts.json
python scripts/evaluation/skill_evolution.py label-pack --dataset .runs/v7-with-facts.json --limit 4000 --out .runs/train-dev-review.json
python scripts/evaluation/skill_evolution.py label-pack --dataset .runs/v7-with-facts.json --splits test --include-test --limit 4000 --out .runs/private-test-review.json
python scripts/evaluation/skill_evolution.py apply-labels --dataset .runs/v7-with-facts.json --reviews .runs/approved-train-dev.json .runs/approved-private-test.json --out .runs/labelled-v7.json
```

没有需要补录的事实时，可直接对原 v7 创建标签包；证据不足的用途不能强行批准。导入后用原 `skill_benchmark.py calibration-pack/calibration-check` 完成结构校准，并用新入口完成质量校准：

```powershell
python scripts/evaluation/skill_evolution.py run --dataset .runs/labelled-v7.json --model-config .runs/model-config.json --skills .runs/baseline-skills.json --split train --repeats 1 --out .runs/calibration-run.json
python scripts/evaluation/skill_evolution.py calibration-pack --dataset .runs/labelled-v7.json --run .runs/calibration-run.json --out-dir .runs/quality-calibration
python scripts/evaluation/skill_evolution.py calibration-check --key .runs/quality-calibration/private-scoring-key.json --review .runs/approved-quality-blind-review.json --out .runs/quality-receipt.json
python scripts/evaluation/skill_evolution.py evolve --dataset .runs/labelled-v7.json --model-config .runs/model-config.json --skills .runs/baseline-skills.json --calibration-report .runs/structural-receipt.json --quality-calibration .runs/quality-receipt.json --holdout-registry .runs/holdout-registry --out-dir .runs/iteration-001
```

推荐模型使用 `RS_BENCHMARK_API_KEY`；裁判使用 `RS_QUALITY_JUDGE_BASE_URL`、`RS_QUALITY_JUDGE_MODEL`、`RS_QUALITY_JUDGE_API_KEY`；优化器使用 `RS_SKILL_OPT_BASE_URL`、`RS_SKILL_OPT_MODEL`、`RS_SKILL_OPT_API_KEY`。凭证只从环境变量读取，远端使用 HTTPS。两种辅助模型可通过各自 `MAX_TOKENS` 控制输出预算；配置不自动继承推荐模型。通过 `--java` 指定已构建的 JDK21 评测进程。

162 项相关回归通过，包括受控择优循环、退步候选拒绝、留出复用阻止，以及既有 Java 到 Python 联通检查。证据见 `verification.json`；实际题集预检见 `preflight-current/result.json`，正式迭代仍被标签与校准门槛阻止。

自动化链路的测试使用受控裁判、人工标签夹具和隔离工具环境，只验证门禁和行为，不构成此真实题集已经完成人审、校准或质量提升的证据。完整运行可能产生较多模型调用，启用前须先确认单次耗时、token 使用和可承受预算。
