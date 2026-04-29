# 工程叙事日志

本文档用于记录本项目中具有复盘价值的工程过程，目标是把开发、调试、优化和验证过程沉淀成适合面试表达的中文材料。

记录重点不是流水账，也不是私有思维链，而是可验证的工程叙事：问题是什么、如何定位、为什么这样解决、如何证明有效、面试时怎么讲。

## 记录原则

- 默认使用中文。
- 每条记录保持简洁，优先写事实和证据。
- 引用具体文件、命令、测试、指标或输出路径。
- 不记录无意义的中间尝试，不堆 raw log。
- 简单机械修改不需要单独记录。

## 条目模板

### YYYY-MM-DD - 任务标题

**任务：**
简要说明这次任务要完成什么。

**遇到的问题：**
说明遇到的技术障碍、歧义、缺陷、数据问题或工程取舍。

**定位方式：**
说明如何诊断问题，引用具体文件、命令、测试、指标或输出证据。

**解决方式：**
说明采用了什么方案，为什么这个方案合理。

**验证结果：**
说明用什么测试、命令、输出文件或指标证明结果有效。

**面试可讲点：**
把这次工作提炼成面试中可以讲的工程能力、系统思维或技术亮点。

## 记录

### 2026-04-28 - CLI Agent 反馈闭环修复

**任务：**
推进 RS Agent 的 CLI 交互闭环，让第二轮用户反馈能真实影响推荐结果，并让 reward 能识别反馈是否产生实际效果。

**遇到的问题：**
CLI smoke 能生成 `session.json`、`session_turns.jsonl` 和 `grpo_rollouts.jsonl`，但两轮 Top-K 完全相同，`changed_after_feedback=false`；同时 reward 只要偏好解析成功就容易给较高 feedback alignment，不能区分“解析了反馈”和“反馈真的改变了推荐”。

**定位方式：**
检查 `rs_core/rsagent/cli.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/workflow/hybrid_demo.py`、`rs_core/rsagent/policy.py`、`rs_core/recsys/ranking.py` 的 feedback 链路，确认 `preferred_sources/preferred_categories` 已解析，但 CLI 使用的配置没有给 feedback source/category 足够的 ranking 权重；初始 smoke 报告见 `outputs/agent_cli_smoke/rs_agent_cli_baseline_comparison.md`。

**解决方式：**
在 `rs_core/rsagent/cli.py` 为 CLI 会话注入不覆盖用户配置的 feedback rank 默认权重，并把模拟反馈改成包含 fresh/again，使第二轮能过滤上一轮已曝光 item；在 `rs_core/rsagent/reward.py` 增加 `feedback_effect_observed` 证据，对后续轮次中没有过滤、boost 或换榜证据的反馈对齐分做上限约束；补充 `tests/test_agent_rollout_schema.py` 和 `tests/test_agent_reward.py` 覆盖换榜与无效反馈降分。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m rs_core.rsagent.cli --config configs/hybrid_demo_electronics_1000_lopo_semantic_title.yaml --limit-users 3 --simulate-two-turn --output-dir agent_cli_smoke_after_fix` 后，报告 `outputs/agent_cli_smoke_after_fix/rs_agent_cli_baseline_comparison.md` 显示 `changed_after_feedback=true`，第二轮 Top-K 从 `B08JQCJZQM/B08HFNNPPJ/...` 变为 `B0B2JJV92T/B08Y1XYLVP/...`，diagnostics 中出现 `feedback_source_semantic`、`excluded_prior_turn_items` 和 `boosts_applied`。直接调用目标测试函数通过，`./.venv/Scripts/python.exe -m compileall -q rs_core tests` 通过；当前环境缺少 pytest，未运行完整 pytest 套件。

**面试可讲点：**
这次工作把 Agent 从“能记录反馈”推进到“反馈能改变策略”的闭环：先定位到配置层 feedback 权重未生效，再用可解释 diagnostics 证明过滤与 boost 发生，最后把 reward 从结果静态打分升级为包含反馈响应性的训练信号，为后续 GRPO rollout 数据打基础。
### 2026-04-28 - 项目文档入口精简与阶段状态同步

**任务：**
整理 Phase 1.5 / Phase 1.6 / Phase 1.7 的文档承接关系，避免历史总结、优化叙事和工程日志之间的信息重复。

**遇到的问题：**
Phase 1.5 历史总结、最新优化判断和工程叙事记录分散在多个文档中，容易让读者误把历史阶段总结当成当前总览，也不利于面试叙事快速定位当前结论。

**定位方式：**
对照 `dic/PHASE_1_5_DEMO_SUMMARY.md`、`dic/OPTIMIZATION_NARRATIVE.md` 和现有 `dic/ENGINEERING_NARRATIVE_LOG.md` 的内容边界，确认 Phase 1.5 应只保留历史总结，Phase 1.6 / 1.7 和最新判断应集中在优化文档，工程日志只记录可复述的过程条目。

**解决方式：**
在 Phase 1.5 文档开头补充阶段说明，在优化文档的当前推荐处补充 Agent 层 demo 的入口方向，并在工程日志中追加一条简短记录；随后将旧实验报告和数据画像移动到 `dic/archive/`，让 `dic/` 根目录只保留核心入口文档，减少重复维护成本。

**验证结果：**
通过核心文档的人工一致性检查，确认 README、实施计划、架构说明、目录说明、Phase 1.5 总结和优化叙事之间的阶段状态一致；`dic/` 根目录保留 7 个核心文档，59 个旧报告和数据画像已归档到 `dic/archive/`；`old_dic/` 已按英文 ASCII 目录整理为 `historical_plans/` 和 `early_data/`，避免中文路径解码异常；未执行新的实验。

**面试可讲点：**
这类工作体现的是文档架构治理能力：不仅能写内容，还能把历史总结、当前判断和过程证据拆分到正确入口，减少信息漂移，让面试叙事更容易复述和验证。

### 2026-04-28 - Agent feedback canonical 固化与 conversational MVP

**任务：**
把已有 CLI feedback smoke 固化成唯一可复现 demo，并把 Agent 从“反馈后再推荐”推进到 deterministic 多轮对话 MVP。

**遇到的问题：**
此前项目已有多份 `agent_cli_*` 输出目录，读者不容易判断哪个是 canonical 证据；同时 Agent 还偏向推荐列表输出，缺少“模糊需求追问、澄清后推荐、解释上一轮、换一批、unsupported 保留”等对话式推荐能力。

**定位方式：**
检查 `rs_core/rsagent/schema.py`、`rs_core/rsagent/policy.py`、`rs_core/workflow/hybrid_environment.py`、`rs_core/rsagent/cli.py` 和 rollout 输出链路，确认已有 session/turn、feedback constraints、reward evidence 和 rollout schema，可以在不改推荐 backbone 的前提下增加 deterministic dialogue manager。

**解决方式：**
新增 `rs_core/rsagent/dialogue.py`，用规则方式规划 `recommend_request`、`clarification_answer`、`ask_explanation`、`preference_feedback`、`unsupported` 等对话意图；扩展 `AgentSession` 保存 `ConversationState`，扩展 `AgentTurn` 保存 `assistant_response`；在 `HybridRecommendationEnvironment.converse()` 中接入对话规划，保持 `step()` 的原 feedback 行为兼容；在 CLI 增加 `--simulate-conversation`，并保留 `--inference-policy off` 作为 deterministic canonical 入口。

**验证结果：**
安装 pytest 后运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_feedback.py tests/test_agent_reward.py tests/test_agent_rollout_schema.py tests/test_agent_dialogue.py`，结果 `19 passed in 0.27s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests` 通过。canonical feedback 入口生成 `outputs/agent_feedback_demo_canonical/`，检查确认 `changed_after_feedback=true`、`feedback_effect_observed=true`、有 boost/filter 证据且 `training_status=deferred_environment_reward_only`。conversational 入口生成 `outputs/agent_conversation_demo_canonical/`，检查确认 turn 2 追问、turn 3 澄清后推荐、turn 4 解释、turn 5 根据反馈再推荐，rollout 逐条保留 deferred training metadata。

**面试可讲点：**
这次工作把 Agent 定位从“推荐包装器”推进到“对话式推荐编排器”：底层仍由传统推荐 backbone 负责召回和排序，Agent 在上层负责识别用户意图、必要时追问、把澄清转成结构化约束、解释推荐依据，并把多轮交互沉淀为 reward / rollout 证据，为后续 Qwen / QLoRA / GRPO 训练路线提供稳定 contract。

### 2026-04-28 - item-level feature rerank 第一版

**任务：**
在 Phase 1.7 source-level rerank 到达边界后，补一个默认关闭、可解释的 item-level feature rerank，用于把多源候选、反馈匹配、popular-only / semantic-only 等信号显式纳入排序诊断。

**遇到的问题：**
统一 semantic boost 和 semantic-only penalty 都没有提升 Top-K hit，说明问题不在 source 整体曝光，而在 item 之间的相对区分；实验初期还误用 `python -m rs_core.workflow.hybrid_demo --config ...`，该模块没有 CLI 入口，导致命令成功退出但没有生成输出。

**定位方式：**
检查 `rs_core/recsys/ranking.py` 和 `scripts/run_hybrid_demo.py`，确认真正实验入口是 `./.venv/Scripts/python.exe scripts/run_hybrid_demo.py --config ...`；对比 `outputs/hybrid_demo_small_electronics_1000_semantic_title*/metrics.json` 与 `ranking_case_summary.json`，确认 item-feature rerank 对 valid/test 和 LOPO 的影响。

**解决方式：**
在 `rank_candidates()` 中增加默认关闭的 `item_feature_rerank`，输出 `feature_score`、`item_features` 和 item_feature rerank events；新增 title semantic 的 valid/test 与 LOPO item-feature 配置，并让 report config summary 显示 `item_feature_rerank` 策略，避免实验报告漏掉关键配置。

**验证结果：**
重新生成 Phase 1.7 baseline 与 Phase 1.8 item-feature 对照后，valid/test `hit_rate_at_k` 保持 0.043478，LOPO `hit_rate_at_k` 保持 0.888889；LOPO `candidate_hit_rank_avg` 从 25.128205 改善到 23.461538，`top1_score_gap_avg` 从 24.742213 降到 24.047873。运行 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py tests/test_agent_feedback.py tests/test_agent_dialogue.py tests/test_agent_rollout_schema.py`，结果 `42 passed in 0.30s`；`./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；独立 verifier 给出 PASS。

**面试可讲点：**
这次工作体现的是从 source-level 调参升级到 feature-level 诊断：当全局 boost / penalty 不能改变同源候选内部顺序时，把多源支持、反馈匹配和单源惩罚显式做成可解释特征。结果没有夸大成 Top-K 提升，而是准确表述为“改善候选池内排名分布，为后续 Agent 反馈和学习排序提供特征接口”。

### 2026-04-28 - rollout 训练样本 contract 与 Qwen harness 对照固化

**任务：**
把已经稳定的 Agent feedback / conversation rollout 往训练前闭环推进：先显式导出 SFT / reward 样本 contract，再验证 Qwen bounded rerank evaluation harness 在无本地模型依赖时也能产出可复现对照结果。

**遇到的问题：**
此前 rollout 已记录 `prompt_context`、`reward_evidence` 和 `diagnostics`，但训练用途仍需要下游再拼字段，缺少“这一轮该学什么、reward 怎么对照”的显式 contract；同时 Qwen harness 虽已有 fake client 改善路径测试，但缺少模型不可用时 fallback 仍能完整生成三模式对照报告的测试，容易把本机环境依赖误当成评估链路能力。

**定位方式：**
检查 `rs_core/rsagent/rollout.py`、`rs_core/rsagent/schema.py`、`rs_core/rsagent/reward.py` 和 `rs_core/workflow/hybrid_demo.py`，确认已有 AgentTurn / AgentSession 字段足够生成训练样本，不需要改推荐 backbone；再检查 `tests/test_hybrid_demo.py` 中已有 `FakeHarnessQwenClient` 测试，确认还需补 `ModelUnavailableError` fallback 路径。

**解决方式：**
在 `turn_to_rollout_record()` 中新增 `training_samples` 字段，拆成 `sft_sample` 和 `reward_sample`：前者包含 user_input、assistant_response、feedback_constraints、candidate_summary、target_action、target_explanation，并用 `allowed_item_ids` 约束 selected_item_ids 只能来自当前候选；后者包含 policy_type、reward、reward_evidence、feedback_effect_observed 和 risk_flags。补充 Qwen harness fallback 测试，验证 deterministic_baseline、rule_feedback_rerank、qwen_feedback_rerank 三种模式即使 Qwen 不可用也会写出 comparison JSON/report 和 inference diagnostics。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_hybrid_demo.py::test_qwen_evaluation_harness_writes_three_mode_comparison tests/test_hybrid_demo.py::test_qwen_evaluation_harness_writes_fallback_comparison_without_model_dependencies tests/test_agent_rollout_schema.py`，结果 `6 passed in 0.23s`；运行 `./.venv/Scripts/python.exe scripts/run_qwen_evaluation_harness.py --config configs/hybrid_demo_electronics_1000_lopo_semantic_title.yaml --limit-users 3 --output-dir outputs/qwen_evaluation_harness_ralph_fallback --qwen-model-id missing-local-qwen` 成功生成 `outputs/qwen_evaluation_harness_ralph_fallback/comparison.json` 和 `comparison.md`，其中 `qwen_feedback_rerank` 的 `fallback_count=1`、`routes={"qwen_local": 1}`。当前 Qwen / QLoRA / GRPO 仍未完整训练落地，本次工作是训练前 contract 与 bounded rerank 对照验证。

**面试可讲点：**
这次工作可以讲成“先把 Agent 交互闭环产品化为可训练数据，再把大模型能力接入约束在候选集内做可回退对照”：不是直接让 LLM 生成商品，而是让它输出 bounded rerank signals，并且在模型不可用时仍保留 deterministic/rule baseline 和诊断产物，体现了推荐系统中对可控性、可复现评估和训练数据 contract 的工程意识。

### 2026-04-28 - 展示层与多角色仿真规划边界预留

**任务：**
把后续真实商品展示、前端交互、多角色模拟客户和动画回放纳入项目规划，同时不打断当前推荐 backbone、Agent feedback、reward / rollout 的主线。

**遇到的问题：**
现有架构主要覆盖数据处理、召回、排序、Agent 对话反馈和训练前 contract，但没有显式说明商品卡展示、前端消费接口、多角色模拟客户和动画回放放在哪一层，后续如果直接开发前端或仿真场景，容易让 UI 字段、模拟客户和推荐内部逻辑耦合。

**定位方式：**
检查 `dic/PROJECT_STRUCTURE.md`、`dic/ARCHITECTURE.md`、`dic/IMPLEMENTATION_PLAN.md`、`dic/README.md` 和 `dic/OPTIMIZATION_NARRATIVE.md`，确认当前文档已覆盖 Agent 主轴和训练路线，但缺少展示层、前端层、仿真层和动画层的目录与边界说明。

**解决方式：**
预留 `rs_core/display/`、`rs_core/simulation/`、`rs_core/animation/` 和 `frontend/` 目录，并在核心文档中补充展示层、前端 / 服务层、仿真 / 动画层的职责：展示层负责商品卡 contract，前端只消费服务与展示接口，模拟客户作为合成交互评估流量，动画层只做 session / rollout 可视化回放。

**验证结果：**
通过目录检查确认 `.gitkeep` 已存在于新增目录；用文档检索确认 `display`、`simulation`、`animation`、`frontend`、商品展示卡、多角色和动画回放等关键条目已出现在 `PROJECT_STRUCTURE.md`、`ARCHITECTURE.md`、`IMPLEMENTATION_PLAN.md`、`README.md` 和 `OPTIMIZATION_NARRATIVE.md`。

**面试可讲点：**
这次调整体现的是从“推荐算法 demo”扩展到“可交互、可展示、可回放、可仿真的 Agent 推荐系统”的架构意识：推荐 backbone 和 Agent 决策仍是主线，商品卡 contract 解决产品化展示，多角色模拟客户用于压力测试交互闭环，动画层用于演示和复盘，但这些外围能力不会污染推荐排序和真实用户评估。

### 2026-04-28 - 商品展示 contract 与前端安全视图

**任务：**
推进 Phase 2 的展示层，把 Agent 最终推荐结果转换成前端可直接消费的 `DisplayResponse` / `ItemDisplayCard` contract，并为后续聊天前端和商品卡 UI 提供 canonical mock 输出。

**遇到的问题：**
已有 `session.json`、`session_turns.jsonl` 和 `grpo_rollouts.jsonl` 同时包含推荐结果、ranking、diagnostics、reward 和 training_samples，适合训练与诊断，但不适合直接交给前端；如果前端直接读 rollout，容易耦合排序分数、reward 证据和内部诊断字段。

**定位方式：**
检查 `rs_core/rsagent/schema.py`、`rs_core/rsagent/rollout.py`、`rs_core/rsagent/cli.py` 和 `rs_core/recsys/types.py`，确认 `AgentDecision.final_items` 已经是展示层最稳定的入口；同时确认商品 title、price、rating、image 等 metadata 不保证齐全，因此 contract 需要 nullable 字段和缺图兜底。

**解决方式：**
在 `rs_core/rsagent/schema.py` 新增 `ItemDisplayCard` 和 `DisplayResponse`，在 `rs_core/display/builder.py` 新增展示层 builder，只从最终推荐 item 和 metadata 派生前端安全字段；在 `rs_core/rsagent/rollout.py` 为每条 rollout 增加 `display_response`，在 `rs_core/rsagent/cli.py` 额外输出 `display_responses.jsonl` 和 `display_demo.json`，同时保持原训练/诊断输出不变。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_agent_rollout_schema.py tests/test_display_contract.py`，结果 `6 passed in 0.16s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 canonical display demo 生成 `outputs/agent_display_demo_canonical/display_responses.jsonl` 和 `display_demo.json`；定向检查 `outputs/agent_display_demo_canonical/grpo_rollouts.jsonl` 中 5 条 `display_response`，确认没有泄漏 `score`、`diagnostics`、`reward_evidence`、`training_samples` 等内部字段。

**面试可讲点：**
这次工作体现的是从算法/Agent demo 走向产品化接口的工程边界设计：训练和诊断需要保留完整内部证据，但前端只需要稳定、安全、可容错的展示 contract。通过派生 `DisplayResponse`，推荐系统可以继续维护可解释诊断和 reward contract，同时让 UI、后续动画回放和多角色仿真复用同一个前端安全视图。

### 2026-04-28 - Phase 2 single-process serving demo

**任务：**
把已有 CLI / conversational Agent demo 封装成轻量 HTTP 服务入口，让后续前端、模拟客户或展示沙盒可以通过 API 调用推荐对话能力。

**遇到的问题：**
项目已有 `HybridRecommendationEnvironment`、`DisplayResponse` 和 CLI canonical demo，但缺少服务层边界；如果直接把 `AgentTurn` 或 rollout 返回给前端，会泄露 ranking、diagnostics、reward 等内部训练/诊断字段。

**定位方式：**
检查 `rs_core/workflow/hybrid_environment.py`、`rs_core/display/builder.py`、`rs_core/rsagent/schema.py` 和 `rs_core/rsagent/cli.py`，确认服务层应复用 `env.converse()` 和 `build_display_record()`，而不是重写推荐逻辑或直接暴露 session/turn 原始结构。

**解决方式：**
新增 `rs_core/serving/service.py`、`schema.py` 和 `app.py`，实现 single-process demo service：`RecommendationService` 在进程内维护 session dict，`/session/start` 使用 UUID 创建独立 session，`/chat` 只返回展示层 `DisplayResponse` contract；新增 `scripts/run_service.py` 和 `requirements-serving.txt`，明确 FastAPI / uvicorn / httpx 依赖与 demo 服务边界。

**验证结果：**
安装 `requirements-serving.txt` 后运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py`，结果 `5 passed in 0.44s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；独立 verifier 给出 PASS，确认服务文件位于 `rs_core/serving/*`、未实现 `/feedback`、unknown session 返回 404，公开响应不含 `ranking`、`diagnostics`、`reward`、`score`。

**面试可讲点：**
这次工作把项目从 CLI 推荐 Agent demo 推进到可 HTTP 调用的服务 contract：底层推荐和 Agent 决策保持不变，服务层只做薄封装和 session 编排，对外统一返回前端安全的展示卡结构。这个边界既能支撑后续 Web Demo / 多角色模拟客户，也避免过早引入数据库、多进程状态和生产部署复杂度。

### 2026-04-28 - 最小 React 商品卡前端 Demo

**任务：**
把 Phase 2 serving demo 接到已有 Vite / React 前端骨架上，实现可交互的聊天输入、商品卡展示和反馈按钮，让推荐 Agent 从 HTTP contract 进一步变成可展示的 Web Demo。

**遇到的问题：**
前端原本主要读取 `mockData` 做静态商品卡展示；接入后端后还需要处理本地 FastAPI 与 Vite 的 CORS、后端重启导致的 session 丢失、真实 demo 数据没有固定 `frontend-demo-user` 这类联调边界。

**定位方式：**
检查 `frontend/src/App.tsx`、`frontend/src/types.ts`、`frontend/src/mockData.ts` 和 `rs_core/serving/app.py`，确认前端应只依赖 `/session/start` 和 `/chat` 的 `DisplayResponse` contract；按用户偏好通过 `omc ask gemini` 审阅前端实现，Gemini 建议保留 mock 降级、按钮转自然语言 feedback、图片兜底，并补 session 失效阻断、价格格式化和聊天记录自动滚动。

**解决方式：**
新增 `frontend/src/api.ts`，让前端启动时创建 session、提交聊天时调用 `/chat`，并继续用 `mockData` 作为后端未启动时的展示兜底；更新 `App.tsx` 渲染对话记录、assistant message、商品卡和 feedback actions；后端补本地 Vite CORS；按 Gemini 审阅意见补充 `Unknown session_id` 后禁用输入并提示刷新、数值价格格式化和消息自动滚动；修正前端默认不传固定 user，让后端选择 demo 数据中的首个用户。

**验证结果：**
运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `7 passed in 0.44s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；启动 `scripts/run_service.py` 和 `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173` 后，用 HTTP 验证 `/health`、默认 `/session/start` 和 `/chat` 返回 `rs_agent_display_v1`，5 个商品卡且响应不含 `ranking`、`diagnostics`、`reward`、`score`，前端页面可加载。

**面试可讲点：**
这次工作把推荐 Agent 从“服务可调用”推进到“用户可交互”：前端没有读取推荐内部字段，而是只消费 `DisplayResponse`，按钮反馈也先转成自然语言走 `/chat`，避免过早扩张 `/feedback` API。通过 Gemini 审阅补齐 session 失效和展示细节，体现了前后端 contract 隔离、Demo 范围控制和跨模型协作把关的工程过程。

### 2026-04-28 - 结构化 feedback API 与前端按钮闭环

**任务：**
把 Web Demo 中的反馈按钮从“转成自然语言再走 `/chat`”升级为结构化 `/feedback` API，让按钮反馈成为可记录、可测试、可扩展的交互事件。

**遇到的问题：**
最小前端 Demo 的按钮反馈虽然可用，但语义依赖英文 prompt 映射，不利于后续统计、回放和训练样本构造；同时前端按钮如何与自由文本 `/chat` 共存、是否携带 item_id、如何处理后端重启后的 session 失效，需要明确边界。

**定位方式：**
检查 `rs_core/serving/schema.py`、`rs_core/serving/service.py`、`rs_core/serving/app.py` 和 `frontend/src/App.tsx`、`frontend/src/api.ts` 的接口边界；按用户要求通过 `omc ask gemini` 审阅前端结构化 feedback 接入方案，Gemini 明确建议输入框只走 `/chat`，快捷按钮只走 `/feedback`，移除 `ACTION_MESSAGES` 自然语言硬编码，并复用 loading 与 session 失效处理。

**解决方式：**
后端新增 `FeedbackRequest` / `FeedbackResponse` 和 `POST /feedback`，支持 `like`、`dislike`、`show_different`、`why` 四种 `action_type`，内部仍复用 `env.converse()` 与 `build_display_record()`，保持输出为 `DisplayResponse`；前端新增 `sendFeedback()`，按钮直接发送 `{session_id, action_type}`，并与 `/chat` 共用 `isLoading`、`applyDisplayUpdate()` 和 `handleRequestError()`，保留后续商品级 `item_id` 反馈的扩展空间。

**验证结果：**
运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `11 passed in 0.51s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；启动后端和前端后，用 HTTP 验证 `/health`、默认 `/session/start`、`/chat` 和 `/feedback`，`/feedback` 返回 `rs_agent_display_v1`、turn_index 更新为 2、5 个商品卡，并确认响应不含 `ranking`、`diagnostics`、`reward`、`score`。

**面试可讲点：**
这次工作把前端反馈从 prompt hack 升级为结构化事件 contract：自由文本仍由 `/chat` 处理，按钮语义由 `/feedback` 表达，后端再统一转入 Agent 决策链路。这样既保持了当前 demo 的轻量实现，又为后续 feedback 日志、session replay、多角色模拟客户和 GRPO reward 样本提供了稳定事件入口。

### 2026-04-28 - session 轨迹安全导出与 replay 基础

**任务：**
在 structured feedback API 之后补齐 `GET /session/{session_id}`，让服务层可以导出当前会话轨迹，为后续 replay、模拟客户评估和前端调试提供安全数据入口。

**遇到的问题：**
`AgentSession.to_dict()` 和 `AgentTurn.to_dict()` 会包含 `ranking`、`diagnostics`、`reward_evidence`、`reward` 等内部诊断与训练字段，不能直接作为公开 API 返回；但如果只返回最后一轮 `DisplayResponse`，又无法支撑多轮 replay 和反馈闭环复盘。

**定位方式：**
检查 `rs_core/serving/service.py`、`rs_core/serving/schema.py`、`rs_core/serving/app.py`、`rs_core/rsagent/schema.py` 和 `rs_core/display/builder.py`，确认安全边界应复用 `build_display_record()`，事件摘要只保留 `turn_index`、`user_input`、`assistant_message` 和 display 索引，不暴露 turn 原始结构。

**解决方式：**
在 `RecommendationService` 新增 `export_session()`，返回 `session_id`、`user_id`、`turn_count`、轻量 `events` 和逐轮 `display_responses`；在 serving schema 中新增 `SessionExportResponse`，并在 FastAPI 中新增 `GET /session/{session_id}`，继续复用统一的 unknown session 404 处理。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `13 passed in 2.41s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 `npm --prefix frontend run build` 通过。新增测试覆盖 chat+feedback 后的 session export、unknown session 404，并递归断言公开响应不含 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`。

**面试可讲点：**
这次工作体现的是“可回放但不泄露内部诊断”的服务 contract 设计：训练和调试侧仍保留完整 AgentTurn / rollout，公开 API 只暴露展示层和轻量事件索引。这样既能支撑后续 session replay、多角色模拟客户和前端调试，又不会把排序分数、reward 证据等内部实现绑死到前端或外部消费者。

### 2026-04-28 - session export 结构化 feedback 事件元数据

**任务：**
增强 `GET /session/{session_id}` 的 replay 事件，让反馈轮次既保留 Agent 实际收到的 `user_input`，也保留原始结构化 `action_type`、`item_id` 和 `comment`。

**遇到的问题：**
上一版 session export 已经安全，但 feedback 事件在导出中只表现为转译后的 prompt，例如 `why? item_id=...`；这对复盘 Agent 行为足够，却不利于后续按按钮类型统计、重放 UI 事件或构造结构化反馈样本。

**定位方式：**
检查 `rs_core/serving/service.py` 和 `tests/test_serving_smoke.py`，确认结构化 feedback 信息在 `/feedback` 请求边界存在，但没有被保留下来；同时确认不应修改 `AgentSession` / `AgentTurn` 训练 schema，以免把服务层事件日志和 Agent 内部状态耦合。

**解决方式：**
在 `RecommendationService` 中新增独立的 `session_events` 轻量列表：`/chat` 记录 `{type: chat}`，`/feedback` 记录 `{type: feedback, action_type, item_id, comment}`；`export_session()` 将这些 metadata 与对应 turn 的 `user_input`、`assistant_message`、`display_response_index` 合并导出。

**验证结果：**
运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `13 passed in 0.59s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；运行 `npm --prefix frontend run build` 通过。测试确认 chat 事件与 feedback 事件类型可区分，feedback 事件包含 `action_type/item_id/comment`，公开响应仍不含内部排序、诊断和 reward 字段。

**面试可讲点：**
这次工作体现的是把“Agent 实际输入证据”和“产品交互事件语义”分层保存：Agent 仍消费转译后的自然语言 prompt，服务层额外保留按钮事件 metadata。这样后续 replay、统计分析和训练样本构造可以使用结构化事件，而不会破坏当前轻量 demo 的 Agent schema。

### 2026-04-28 - Gemini 实现 Session Replay 前端闭环

**任务：**
在已有 React 商品卡 Demo 中接入 `GET /session/{session_id}`，把 chat、feedback、display response 串成可视化 Session Replay 时间线，并按用户要求由 Gemini 负责前端实现。

**遇到的问题：**
后端已经能安全导出 session 轨迹，但前端还只能看到当前轮商品卡，不能复盘多轮对话、按钮反馈和每轮推荐变化；同时项目要求前端实现优先交给 Gemini，而不是由我先改再让 Gemini 审阅。

**定位方式：**
对照 `frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts` 和后端 `SessionExportResponse` contract，明确前端只允许消费 `events` 与 `display_responses`，不能读取 `ranking`、`diagnostics`、`reward`、`score` 等内部字段；通过 Gemini CLI 直接执行前端实现，再由我做边界检查和验证。

**解决方式：**
由 Gemini 在 `frontend/src/types.ts` 增加 `SessionExportEvent` / `SessionExportResponse` 类型，在 `frontend/src/api.ts` 增加 `fetchSessionExport()`，并在 `App.tsx` 增加 `Replay Session` 按钮、loading/error 状态和只读 timeline：每轮展示 turn、chat/feedback 类型、feedback metadata、assistant message 和对应商品快照。

**验证结果：**
运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m pytest tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `13 passed in 0.57s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；检索 `frontend/src` 确认没有引用 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`；通过临时本地服务 HTTP 验证 chat→feedback→session export，导出包含 `event_types=[chat, feedback]` 且无内部字段泄露。

**面试可讲点：**
这次工作把推荐 Agent demo 从“当前轮展示”推进到“完整交互轨迹可回放”：用户输入、结构化反馈、Agent 回复和商品卡变化都能按 session timeline 复盘。工程上体现了前后端 contract 隔离、内部诊断字段保护，以及用 Gemini 承担前端实现、我负责接口边界和验收整合的协作流程。

### 2026-04-28 - 多角色模拟的角色内在模型基础层

**任务：**
把“多角色模拟客户”从一次性测试脚本调整为后续模拟场景的角色内在基础层，先实现可复用的角色画像、状态和 deterministic 行为策略。

**遇到的问题：**
如果直接做批量 simulated session runner，容易把多角色模拟降级成 smoke test；但项目后续目标是类似沙盒/游戏场景的多角色客户，每个角色需要有稳定人格、购物目标、偏好、记忆、反馈风格和状态演化，才能支撑 replay、动画和更真实的 Agent 评估。

**定位方式：**
对照已有 `rs_core/simulation/` 骨架和当前 `DisplayResponse` contract，确认 simulation 层应先消费前端安全展示数据，而不是读取推荐内部 ranking/reward；同时根据用户反馈明确：角色内在状态应优先于批量评估脚本。

**解决方式：**
新增 `rs_core/simulation/schema.py`，定义 `SimulatedCustomerRole`、`RoleState`、`RoleActionType`、`RoleAction`；新增 `policy.py`，用 deterministic `RolePolicy` 根据角色偏好、预算敏感度、负偏好和当前 display items 选择 chat、why、show_different、dislike、accept 等动作；新增 `presets.py`，提供通勤实用型、礼物购买型、价格敏感型三个内置角色，并通过 `rs_core/simulation/__init__.py` 导出。

**验证结果：**
新增 `tests/test_simulation_roles.py` 覆盖初始 prompt、preset 注册、已看商品状态更新、无商品时追问、有强匹配商品时接受、谨慎角色要求解释、不同 feedback style 产生不同动作；运行 `./.venv/Scripts/python.exe -m pytest tests/test_simulation_roles.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `20 passed in 0.57s`；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过。

**面试可讲点：**
这次工作体现的是把多角色模拟从“跑几条 prompt”提升为“角色内在模型”：角色画像、目标、偏好、记忆和反馈风格决定下一步行为，且只依赖安全 `DisplayResponse`。这为后续多角色沙盒、session replay 动画、模拟客户评估和 LLM-driven role simulation 留出了清晰扩展点。

### 2026-04-28 - Simulation Scene 后端契约与前端展示闭环

**任务：**
把角色内在模型接到真实 Agent 服务层，生成可供前端展示的 simulation scene，并按用户要求由 Gemini 实现前端场景面板。

**遇到的问题：**
角色画像和策略已经存在，但还没有驱动真实 Agent session；前端也无法展示“角色如何带着目标、偏好和反馈风格与推荐 Agent 交互”的完整场景。如果前端直接造假数据，会削弱 replay 和评估价值；如果后端直接暴露 AgentTurn，则又会泄露 ranking/reward 等内部字段。

**定位方式：**
检查 `rs_core/simulation/schema.py`、`policy.py`、`presets.py`、`rs_core/serving/service.py` 和 `SessionExportResponse` contract，确认最稳妥的连接方式是让 runner 复用 `RecommendationService.chat()` / `feedback()` 和 `export_session()`，输出 role、state、actions、session 四段安全 scene contract。

**解决方式：**
新增 `rs_core/simulation/runner.py`，实现 `run_simulation_scene()`：角色先发 `initial_prompt()`，随后由 `RolePolicy` 根据每轮 `DisplayResponse` 选择 chat、feedback、show_different、why、accept 等动作，最终导出 `scene_id`、角色画像、角色状态、动作时间线和安全 session export；在 FastAPI 中新增 `POST /simulation/scene`，并让 Gemini 在前端新增 Simulation Scene 面板，支持选择 `commuter_practical`、`gift_buyer`、`price_sensitive`，展示角色卡、状态卡、动作时间线和 session summary。

**验证结果：**
新增 `tests/test_simulation_runner.py` 覆盖 runner contract、API endpoint 和 unknown role；运行 `./.venv/Scripts/python.exe -m pytest tests/test_simulation_runner.py tests/test_simulation_roles.py tests/test_serving_smoke.py tests/test_display_contract.py`，结果 `23 passed in 0.60s`；运行 `npm --prefix frontend run build` 通过；运行 `./.venv/Scripts/python.exe -m compileall -q rs_core tests scripts` 通过；检索 `frontend/src` 确认没有引用 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`；本地 HTTP 验证 `POST /simulation/scene` 返回 `role_id=commuter_practical`、`turn_count=3`、`final_action=show_different` 且无内部字段泄露。

**面试可讲点：**
这次工作把项目从“单个用户手动 demo”推进到“角色驱动的可展示模拟场景”：角色内在状态决定交互行为，Agent 服务生成真实推荐与反馈轨迹，前端以 scene 面板展示角色、状态、动作和商品卡回放。它为后续多角色沙盒、动画展示、LLM 驱动角色和批量模拟评估提供了可复用 contract。

### 2026-04-29 - 端到端推荐 Agent 演示闭环聚合

**任务：**
把已有服务层、展示层和 React 前端推进成可一键演示的多轮闭环：用户需求进入 Agent，服务返回 `DisplayResponse` 商品卡，反馈后第二轮推荐发生变化，并能在前端按商品提交喜欢/不喜欢。

**遇到的问题：**
项目已有 `/chat`、`/feedback`、session replay 和商品卡前端，但面试演示仍需要人工分多步操作；同时测试环境当前缺少 `pytest` 和 `fastapi`，不能直接跑完整 HTTP 测试套件。

**定位方式：**
检查 `rs_core/serving/service.py`、`rs_core/serving/app.py`、`rs_core/display/builder.py`、`frontend/src/App.tsx` 和 `tests/test_serving_smoke.py`，确认可复用 `RecommendationService.chat()`、`feedback()` 与 `DisplayResponse`，不需要让前端读取 rollout、ranking、diagnostics 或 reward 字段。

**解决方式：**
在服务层新增 `run_demo_roundtrip()` 和 `/demo/e2e`，聚合 start session、首轮 chat、结构化 feedback 和变化摘要；前端新增一键闭环按钮，并把商品卡上的喜欢/不喜欢绑定到具体 `parent_asin`；补充 smoke 测试用例覆盖两轮展示、turn_index 递增、商品变化和内部字段不外泄。

**验证结果：**
补齐 serving/test 依赖后，运行 `python -m pytest tests/test_serving_smoke.py tests/test_display_contract.py -q`，结果 `15 passed in 1.35s`；运行 `python -m compileall -q rs_core tests scripts` 通过；运行 `npm --prefix frontend run build` 通过。测试覆盖 `/demo/e2e` 的两轮 `DisplayResponse`、`turn_index` 递增、商品集合变化、unknown feedback 422，以及公开响应不含 `ranking`、`diagnostics`、`reward`、`reward_evidence`、`score`。

**面试可讲点：**
这次工作把推荐 Agent 从“有接口、有前端”推进到“可一键复现闭环”：服务端用薄 orchestration 串起现有推荐和反馈能力，前端只消费展示 contract，变化摘要用于证明反馈确实影响下一轮推荐。这个实现兼顾了演示效率、前后端边界隔离和后续训练/回放数据的可解释性。

