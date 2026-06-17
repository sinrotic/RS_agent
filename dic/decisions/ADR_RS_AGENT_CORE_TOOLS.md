# RS Agent 核心隐藏业务工具集 ADR

- 日期：2026-06-04
- 状态：implemented（2026-06-04）
- 决策范围：RS Agent 对外可用工具边界、对话规划默认工具链、public display 安全边界

## 背景

最初讨论过参考 Claude Code 的 ToolSearch，把更多工具按需挂到 Agent 后台。但当前 RS Agent 的工具数量和复杂度远低于 Claude Code，且推荐系统工具天然有业务语义和安全边界：召回、排序、RAG、反馈、展示都应由后端治理，不能让前台 Agent 直接面对 `itemcf_strong`、`semantic`、`catalog_constraint_search`、`deepfm_rank_candidates` 等工程 artifact。

如果把底层方法名直接暴露为 Agent 工具，会带来三个问题：

1. 对话 Agent 和召回/排序实现强耦合，后续替换模型或召回源会影响前台工具契约。
2. 工具输出容易携带 `score_trace`、`feature_rows`、`source`、diagnostics 等内部字段，增加 public payload 泄露风险。
3. 面试叙事上会显得像“LLM 直接调算法模块”，而不是一个有边界的推荐 Agent 工具层。

## 决策

正式 Agent-facing 工具收敛为一组高层隐藏业务工具。2026-06-10 起新增 `query_rag`，用于召回前可选的 query planning / 属性扩展 / 澄清辅助；它不直接返回候选，也不替代 `retrieve_candidates` 或 `rank_candidates`。

| 工具 | 阶段 | 默认推荐流程 | public payload | 说明 |
|------|------|--------------|----------------|------|
| `get_user_context` | context | 是，pre | 否 | 读取 session、最近 turn、约束、已展示/喜欢/不喜欢 item 的 compact 摘要 |
| `query_rag` | query_planning | 可选，pre | 否 | 召回前按需检索 compact 商品知识 hints，用于增强语义 query、属性扩展或澄清规划 |
| `retrieve_candidates` | candidate_generation | 是，pre | 否 | 获取候选 item ids 和候选摘要，内部复用召回/检索逻辑 |
| `rank_candidates` | ranking | 是，post | 否 | 对候选排序并返回 ranked item ids / summary，内部可复用 DeepFM / hybrid ranker |
| `get_item_evidence` | evidence | 是，post；解释请求也可用 | 否 | 从 RAG context 或 display-safe item card 抽取候选内证据 |
| `record_user_feedback` | feedback | 否 | 否 | 显式反馈写入 session constraints，不在普通推荐流程默认执行 |
| `build_recommendation_slate` | response_composition | 是，post | 是 | 构建展示安全 slate，必须复用 display builder 和 validator |

默认推荐工具链：

```text
get_user_context
  ↓
query_rag（可选：场景复杂、属性含糊或需要商品知识扩展时）
  ↓
retrieve_candidates
  ↓
后端 recommendation backbone 生成 / 更新 turn
  ↓
rank_candidates
  ↓
get_item_evidence
  ↓
build_recommendation_slate
```

解释请求工具链：

```text
get_user_context
  ↓
get_item_evidence
```

`record_user_feedback` 只在显式反馈入口或后续需要独立记录反馈事件时调用，避免和现有 dialogue plan 的 `merge_feedback()` 重复写入。

## 不变性边界

- LLM 不直接编造商品，也不绕过推荐 backbone。
- `query_rag` 只输出 compact query planning hints，不输出候选集合，不作为排序输入替代，也不向 public payload 暴露 raw evidence、score、source path 或 diagnostics。
- `retrieve_candidates` / `rank_candidates` 不向 Agent 输出 raw source score、path diagnostics、`feature_rows` 或完整 score trace。
- `get_item_evidence` 只选择候选内证据，不修改 `candidates`、`ranking` 或 `final_items`。
- `build_recommendation_slate` 是唯一允许 public payload 的工具，输出必须通过 `validate_public_display_payload()`。
- public display 不允许出现 `diagnostics`、`score`、`score_trace`、`ranking`、`reward_evidence`、`agent_tool_trace`、`feedback_source`、`recall source`、training/evaluation 字段或内部工具名；`source` / `training` / `reward` 这类普通英文词只允许作为商品或助手可见自然文本出现，不能作为内部字段或血缘信号暴露。

## 代码落点

- 工具契约与 manifest：`rs_core/rsagent/tools.py`
- 对话规划默认工具链：`rs_core/rsagent/dialogue.py`
- 工具 dispatch 与内部复用：`rs_core/workflow/hybrid_environment.py`
- public display allowlist / forbidden terms：`rs_core/display/builder.py`
- 测试覆盖：`tests/test_agent_tools.py`、`tests/test_agent_capability_manifest.py`、`tests/test_agent_dialogue.py`、`tests/test_agent_runtime.py`、`tests/test_display_contract.py`、`tests/test_serving_smoke.py`

## 验证

历史版本曾使用项目默认 `.venv` 完成验证：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py tests/test_agent_dialogue.py tests/test_agent_runtime.py -q
# 46 passed

D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_display_contract.py tests/test_serving_smoke.py -q
# 53 passed

D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_rag_core.py tests/test_agent_feedback.py tests/test_feedback_rerank.py -q
# 34 passed

D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py tests/test_agent_dialogue.py tests/test_agent_runtime.py tests/test_display_contract.py tests/test_serving_smoke.py tests/test_agent_capability_manifest.py -q
# 101 passed
```

`query_rag` 增量改造与 public validator 收口已使用项目默认 `.venv` 完成回归验证：

```bash
D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe -m pytest tests/test_agent_tools.py tests/test_rag_core.py tests/test_agent_runtime.py tests/test_agent_capability_manifest.py tests/test_agent_dialogue.py tests/test_display_contract.py tests/test_serving_smoke.py -q
# 227 passed
```

## 后续风险与演进

当前私有 `_dispatch_agent_tool_call()` 中仍保留部分 legacy 分支，正常入口会先经过 manifest 校验，旧工具不会被正式 dialogue plan 触达。后续可进一步删除旧分支，或在私有 dispatch 顶部加入二次 `get_agent_tool_spec()` 校验，让边界更硬。

如果未来工具数量显著增加，再考虑类似 ToolSearch 的 deferred discovery；当前阶段保持少量常驻核心隐藏工具更清晰、更容易测试和面试表达。

## 面试可讲点

这次改造可以讲成“把推荐 Agent 的工具层产品化”：不是把算法模块原样暴露给 LLM，而是把召回、排序、RAG、反馈和展示封装成少量稳定业务工具；其中 `query_rag` 负责召回前语义规划，`get_item_evidence` 负责排序后候选解释。LLM 负责对话与调度，推荐系统负责真实候选、排序和展示安全。这样既降低前台复杂度，也通过 public payload validator 把内部诊断和用户可见内容隔离开。
