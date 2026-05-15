# RS_agent：Agent 主轴 + 传统推荐 backbone

## 项目定位

这个项目的核心叙事不是“纯大模型端到端推荐”，而是**以 Agent 决策为主轴、以传统推荐 backbone 为底座**的混合推荐系统。

我们保留推荐系统里最容易解释、也最适合面试表达的主链路：

- 召回：先缩小候选范围
- 排序：再做优先级判断
- 规则与约束：去重、过滤、频控、黑白名单等
- Agent：在候选结果之上做最终选择、解释和反馈响应

训练层采用 `Qwen3.5-4B + 8-bit QLoRA SFT + GRPO` 作为规划路线和能力补强方向，但**不把它写成已完整落地的系统能力**。当前已经补齐商品展示卡、轻量 HTTP 服务、React Web Demo、Session Replay、多角色模拟客户和模型驱动模拟用户第一版；这些属于展示与仿真评估能力，不改变当前推荐 backbone + Agent 的主线。

---

## 当前状态

### 已完成

- **Phase 1.5**：小样本可诊断 hybrid demo 已完成
- **Phase 1.6**：semantic / text recall 第一版已完成
- **Phase 1.7**：rerank / 排序曝光诊断已形成阶段性结论：source-level 调参接近边界，不应继续盲目调 semantic exposure
- **Phase 1.8**：item-level feature rerank 第一版已完成，Top-K 命中不变，但 LOPO target 平均排名从 25.13 改善到 23.46，说明它更适合作为可解释排序特征入口而不是单独的 hit-rate 提升方案
- **Phase 1.9**：DSSM-style / YouTubeDNN-style 双塔向量召回旁路已完成第一版，包含 PyTorch 训练 artifact、向量索引、默认关闭配置和 strict promotion gate；当前只作为实验旁路，不默认替代主路。现有证据是训练 `limit_users=10` 与评估 `limit_users=30` 的 smoke，不是完整 10k 双塔结论，且两类双塔 smoke 均未通过晋升 gate
- **CLI Agent feedback canonical demo**：已在 2026-04-28 固化为可复现入口，产物见 `outputs/agent_feedback_demo_canonical/`
- **Conversational Agent MVP**：已支持 deterministic 多轮对话雏形，包括模糊请求追问、澄清后更新约束、解释上一轮推荐、换一批推荐和 unsupported 文本保留，产物见 `outputs/agent_conversation_demo_canonical/`
- **Phase 2 展示与服务闭环**：已完成 `DisplayResponse` 商品卡 contract、single-process HTTP 服务、结构化 `/feedback`、`GET /session/{session_id}` 安全导出和 React Web Demo 第一版
- **Session Replay 与一键 E2E Demo**：已完成前端 Session Replay 时间线和 `/demo/e2e` 闭环入口，可证明反馈后第二轮推荐发生变化
- **Phase 3 多角色仿真第一版**：已完成角色内在模型、Simulation Scene、批量 Simulation Evaluation 和模型驱动模拟用户策略，产物包括 `simulation_batch.json`、`metrics.json` 和中文评估报告

### 进行中

- 训练与评估链路继续向稳定闭环演进，后续重点是把真实 Web Demo 与 Simulation 产生的 session / feedback / replay 轨迹整理成可校验的 SFT、reward 和 GRPO 对照样本

---

## 当前 canonical demo 入口

### Agent feedback demo

```bash
./.venv/Scripts/python.exe -m rs_core.rsagent.cli \
  --config configs/hybrid_demo_electronics_1000_lopo_semantic_title.yaml \
  --limit-users 3 \
  --simulate-two-turn \
  --output-dir agent_feedback_demo_canonical \
  --inference-policy off
```

产物：`outputs/agent_feedback_demo_canonical/rs_agent_cli_baseline_comparison.md`

### Conversational Agent MVP demo

```bash
./.venv/Scripts/python.exe -m rs_core.rsagent.cli \
  --config configs/hybrid_demo_electronics_1000_lopo_semantic_title.yaml \
  --limit-users 3 \
  --simulate-conversation \
  --output-dir agent_conversation_demo_canonical \
  --inference-policy off
```

产物：`outputs/agent_conversation_demo_canonical/rs_agent_cli_baseline_comparison.md`

当前 conversational 能力是 deterministic dialogue manager：用于证明 Agent 能追问、澄清、解释和根据反馈再推荐；它不是完整 LLM chatbot，也不代表 Qwen / QLoRA / GRPO 训练已经完成。

### Phase 1.8 item-feature rerank 对照

```bash
./.venv/Scripts/python.exe scripts/run_hybrid_demo.py \
  --config configs/hybrid_demo_electronics_1000_lopo_semantic_title_item_feature.yaml
```

产物：`outputs/hybrid_demo_small_electronics_1000_lopo_semantic_title_item_feature/metrics.json`

当前结论：Top-K hit 与 Phase 1.7 title baseline 持平，但 LOPO target 平均排名从 25.128205 改善到 23.461538。

## 当前不做

- 不把双塔向量召回默认并入主路；DSSM / YouTubeDNN 需要通过 valid/test、LOPO sanity 和 latency strict gate 后才进入人工晋升评审
- 不在本批实现 Node2Vec / DeepWalk、MIND / SDM、TDM、DeepFM / NCF；这些保留为后续召回 / 粗排路线规划，其中 DeepFM / NCF 更偏打分或重排，不直接当高效 Top-N 主召回
- 不把当前 single-process demo 写成全量工业化服务
- 不夸大 `Qwen3.5-4B + 8-bit QLoRA SFT + GRPO` 已经完整训练落地
- 不把 `old_dic` 作为当前规划依据；它仅是历史草稿

---

## 推荐阅读顺序

1. `ARCHITECTURE.md`
2. `IMPLEMENTATION_PLAN.md`
3. `PROJECT_STRUCTURE.md`
4. `RANKING_LONG_RUNNING_EXPLORATION_PLAN.md`
5. `OPTIMIZATION_NARRATIVE.md`
6. `PHASE_1_5_DEMO_SUMMARY.md`
7. `ENGINEERING_NARRATIVE_LOG.md`

---

## 一句话总结

这个项目要证明的是：**Agent 负责编排和决策，传统推荐 backbone 负责召回和排序，训练层负责补强表达与对齐**。