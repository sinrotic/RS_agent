# RS_agent：Agent 主轴 + 传统推荐 backbone

## 项目定位

这个项目的核心叙事不是“纯大模型端到端推荐”，而是**以 Agent 决策为主轴、以传统推荐 backbone 为底座**的混合推荐系统。

我们保留推荐系统里最容易解释、也最适合面试表达的主链路：

- 召回：先缩小候选范围
- 排序：再做优先级判断
- 规则与约束：去重、过滤、频控、黑白名单等
- Agent：在候选结果之上做最终选择、解释和反馈响应

训练层采用 `Qwen3.5-4B + 8-bit QLoRA SFT + GRPO` 作为规划路线和能力补强方向，但**不把它写成已完整落地的系统能力**。后期规划会补商品展示卡、轻量前端、多角色模拟客户和动画回放层，但这些属于展示与仿真评估能力，不改变当前推荐 backbone + Agent 的主线。

---

## 当前状态

### 已完成

- **Phase 1.5**：小样本可诊断 hybrid demo 已完成
- **Phase 1.6**：semantic / text recall 第一版已完成
- **Phase 1.7**：rerank / 排序曝光诊断已形成阶段性结论：source-level 调参接近边界，不应继续盲目调 semantic exposure
- **Phase 1.8**：item-level feature rerank 第一版已完成，Top-K 命中不变，但 LOPO target 平均排名从 25.13 改善到 23.46，说明它更适合作为可解释排序特征入口而不是单独的 hit-rate 提升方案
- **CLI Agent feedback canonical demo**：已在 2026-04-28 固化为可复现入口，产物见 `outputs/agent_feedback_demo_canonical/`
- **Conversational Agent MVP**：已支持 deterministic 多轮对话雏形，包括模糊请求追问、澄清后更新约束、解释上一轮推荐、换一批推荐和 unsupported 文本保留，产物见 `outputs/agent_conversation_demo_canonical/`

### 进行中

- 训练与评估链路继续向稳定闭环演进，后续重点是让 Agent 层对话/反馈信号进入更稳定的训练样本和 reward 对照

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

- 第一阶段不做双塔
- 不把系统直接推进到全量工业化服务
- 不夸大 `Qwen3.5-4B + 8-bit QLoRA SFT + GRPO` 已经完整落地
- 不把 `old_dic` 作为当前规划依据；它仅是历史草稿

---

## 推荐阅读顺序

1. `ARCHITECTURE.md`
2. `IMPLEMENTATION_PLAN.md`
3. `PROJECT_STRUCTURE.md`
4. `OPTIMIZATION_NARRATIVE.md`
5. `PHASE_1_5_DEMO_SUMMARY.md`
6. `ENGINEERING_NARRATIVE_LOG.md`

---

## 一句话总结

这个项目要证明的是：**Agent 负责编排和决策，传统推荐 backbone 负责召回和排序，训练层负责补强表达与对齐**。