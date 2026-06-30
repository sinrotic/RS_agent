# RS Agent 旧路径 import census

## 1. 目标

本文档记录 `RS_AGENT_POST_MIGRATION_HARDENING_PLAN.md` Phase 1 的旧路径 import census 结果，用于后续退役治理、compatibility facade whitelist 和物理迁移窗口准入。

本 census 不把旧路径 import 直接等同于违规：当前迁移策略允许 canonical 新入口通过少量 compatibility facade 承接存量实现。但所有允许项必须可解释、可测试、可退役，不能继续扩展成第二套主线。

---

## 2. 扫描范围与命令

扫描范围：

- `rs_core/data`
- `rs_core/online`
- `rs_core/agent`
- `rs_core/offline`
- `services`
- `scripts`
- `tests`

旧路径集合：

- `rs_core/artifacts`
- `rs_core/training`
- `rs_core/evaluation`
- `rs_core/recsys`
- `rs_core/serving`
- `rs_core/workflow`
- `rs_core/simulation`
- `rs_core/display`

已归档且不再纳入 active legacy implementation source 的目录 / 空包 / marker：`rs_core/dataproc`、`rs_core/features`、`rs_core/animation`、`rs_core/llm`。

复现命令：

```bash
.venv/Scripts/python.exe - <<'PY'
from __future__ import annotations
import ast
from collections import Counter, defaultdict
from pathlib import Path
root = Path.cwd()
legacy_roots = [
    'rs_core.artifacts','rs_core.training','rs_core.evaluation',
    'rs_core.recsys','rs_core.serving','rs_core.workflow',
    'rs_core.simulation','rs_core.display'
]
scan_roots = ['rs_core/data','rs_core/online','rs_core/agent','rs_core/offline','services','scripts','tests']
rows=[]
for sr in scan_roots:
    base=root/sr
    if not base.exists():
        continue
    for path in base.rglob('*.py'):
        tree=ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            mods=[]
            if isinstance(node, ast.Import):
                mods=[a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods=[node.module]
            for mod in mods:
                for legacy in legacy_roots:
                    if mod == legacy or mod.startswith(legacy + '.'):
                        rows.append((path.relative_to(root).as_posix(), mod, legacy))
                        break
by_scan=Counter()
by_legacy=Counter()
examples=defaultdict(list)
for path, mod, legacy in rows:
    for sr in scan_roots:
        if path.startswith(sr):
            by_scan[sr]+=1
            key=(sr, legacy)
            if len(examples[key]) < 5:
                examples[key].append(f'{path} -> {mod}')
            break
    by_legacy[legacy]+=1
print('SUMMARY_BY_SCAN')
for k in scan_roots:
    print(f'{k}: {by_scan[k]}')
print('\nSUMMARY_BY_LEGACY')
for k, v in by_legacy.most_common():
    print(f'{k}: {v}')
print('\nEXAMPLES')
for key in sorted(examples):
    print(f'[{key[0]} / {key[1]}]')
    for item in examples[key]:
        print(f'- {item}')
PY
```

---

## 3. 汇总结果

### 3.1 按扫描区域统计

| 扫描区域 | 旧路径 import 数量 | 当前解释 | 治理动作 |
| --- | ---: | --- | --- |
| `rs_core/data` | 0（针对已迁移的 `dataproc` / artifact 旧路径） | data canonical implementation 已承接 pipelines 与 artifacts | 继续用 architecture boundary 防止旧路径回流 |
| `rs_core/online` | 6 | online canonical facade 承接 `recsys`、`workflow`、serving schema | 保留 whitelist，Phase 2 做 recall/ranking/runtime parity 后清零 |
| `rs_core/agent` | 0（针对已删除的 `agent_runtime`、`rsagent` 与 `simulation` 旧路径；仍有 `recsys/rag` 兼容项） | agent canonical owner 已承接 generic runtime、adapters、dialogue、planner、tools、memory、runtime、feedback、rerank、model client 与 contracts；Agent simulation facade 已改指 `rs_core.offline.simulation` | 继续用 architecture boundary 防止 `agent_runtime` / `rsagent` / `simulation` 旧路径回流 |
| `rs_core/offline` | 1 | training/evaluation/simulation 均已迁入 canonical owner；当前剩余旧路径 import 来自 offline multi-turn SFT 复用 serving recommendation service 的登记边界 | 保持 whitelist-only，并用 path-not-exists guard 防止 `rs_core/training` 回流 |
| `services` | 0 | 外部 services package 已物理删除；online/agent 入口迁到 `rs_core.serving.api.*_app`，data/offline worker 迁到 `rs_core.*.runtime.worker` | 禁止恢复 `services` 为新业务入口；新增入口必须落在对应 `rs_core` runtime/api 下 |
| `scripts` | 29 | 历史 CLI 仍有 recsys/workflow/serving/display 等旧路径依赖；training scripts 已切 `rs_core.offline.training.*` | Phase 1 标记退役等级；Phase 5/7 后逐步替换或降级为手动脚本 |
| `tests` | 190 | 大量历史测试仍覆盖 recsys/workflow/serving/display 等旧实现和兼容层；training/evaluation/simulation tests 已切 canonical offline import | 保留作为 parity/legacy coverage；新增 hardening tests 防止新依赖扩散 |

### 3.2 按旧路径统计

| 旧路径根 | import 数量 | 主要来源 | 当前退役等级 |
| --- | ---: | --- | --- |
| `rs_core.recsys` | 133 | online facade、RAG facade、recall/ranking/vectorstore/历史测试 | C |
| `rs_core.rsagent` | 0（主代码和测试调用点已清零；active package 已删除） | dialogue、planner、tools、explanation、memory、runtime、feedback、rerank、model client、contract 等真实实现已迁入 `rs_core.agent.*`；architecture boundary 增加 path-not-exists guard 防恢复 | A / retired |
| `rs_core.workflow` | 46 | online runtime facade、训练/评估脚本、pool500/ranking 历史测试 | C |
| `rs_core.serving` | 65 | services schema compatibility、旧 serving tests、少量脚本 | B |
| `rs_core.training` | 0（主代码、脚本和测试调用点已清零；active package 已删除） | 训练配置、数据契约、Qwen/SFT/GRPO/GPT SFT、judge、reward 与 multi-turn SFT generator 真实实现已迁入 `rs_core.offline.training`；architecture boundary 增加 path-not-exists guard 防恢复 | A / retired |
| `rs_core.simulation` | 0（主代码和测试调用点已清零；active package 已删除） | simulation schema/policy/presets/runner/model client 真实实现已迁入 `rs_core.offline.simulation`；`rs_core.agent.simulation` 仅作为 Agent sandbox facade 指向 canonical offline implementation | A / retired |
| `rs_core.agent_runtime` | 0（主代码和测试调用点已清零；active package 已删除） | generic runtime、adapter、contracts 真实实现已迁入 `rs_core.agent.runtime_core` / `rs_core.agent.adapters`；architecture boundary 增加 path-not-exists guard 防恢复 | A / retired |
| `rs_core.recsys.semantic_description` | 0（主代码和测试调用点已清零；active package 已删除） | semantic description scoring/retrieval/engine/store 真实实现已迁入 `rs_core.agent.rag.semantic_description`；architecture boundary 增加 path-not-exists guard 防恢复 | A / retired |
| `rs_core.dataproc` | 0（主代码调用点已清零；已从 active legacy roots 移除） | 真实实现迁入 `rs_core.data.pipelines`，data scripts/tests 已切新路径 | B |
| `rs_core.artifacts` | 0（主代码调用点已清零；旧 compatibility `__init__.py` 已删除，仅治理文档/contract root 常量保留） | manifest/resolver 真实实现已迁入 `rs_core.data.artifacts`，脚本和测试已切到新路径；architecture boundary 增加 path-not-exists guard 防恢复 | A / retired |
| `rs_core.evaluation` | 0（主代码和测试调用点已清零；active package 已删除） | Agent evaluation artifact / scorecard 真实实现已迁入 `rs_core.offline.evaluation`；architecture boundary 增加 path-not-exists guard 防恢复 | A / retired |
| `rs_core.display` | 3 | display contract tests | B |

---

## 4. 允许的 compatibility facade 类型

当前允许的旧路径 import 必须属于以下类型之一：

1. **canonical facade 承接存量实现**：例如 ranking / RAG 仍有已登记 facade；`rs_core.recsys.recall`、`rs_core.rsagent`、`rs_core.training`、`rs_core.evaluation` 与 `rs_core.simulation` 已不再属于允许项，active package 已删除。
2. **已收敛的服务入口**：原 `services/*` package 已删除；split HTTP 入口改为 `rs_core.serving.api.online_app` / `rs_core.serving.api.agent_app`，Data/Offline worker 改为 `rs_core.data.runtime.worker` / `rs_core.offline.runtime.worker`。
3. **legacy/parity tests**：历史测试可以直接覆盖旧实现，用于物理迁移前对照。
4. **手动/历史 CLI**：`scripts/recall`、部分 `scripts/training`、`scripts/evaluation` 可暂留，但不得作为新主入口；长期入口应使用 `rs_core.data.runtime.worker`、`rs_core.offline.runtime.worker` 或新 engine wrapper。

---

## 5. 当前重点风险

- `scripts` 仍有 29 处旧路径 import，说明脚本层是后续退役治理重点；training、Agent evaluation 与 simulation evaluation 已完成 canonical import 收束。
- `tests` 有 190 处旧路径 import，说明测试还同时承担 recsys/workflow/serving/display legacy 行为保护；后续不能简单删除，应先建立 new-vs-old parity tests。
- `services` package 已物理删除；后续风险从“外部 service wrapper 变厚”转为“有人恢复 `services` 作为新入口”，需由 grep/import guard 阻止。
- `rs_core/online`、`rs_core/agent`、`rs_core/offline` 里的旧路径 import 只能出现在白名单 facade 文件中；新增业务文件不得继续直连旧实现。

---

## 6. 删除前 grep/import 证据模板

每个旧目录进入删除窗口前，需要至少提供：

```bash
.venv/Scripts/python.exe -m pytest tests/contracts/test_architecture_migration_boundaries.py -q
.venv/Scripts/python.exe -m ruff check rs_core services tests/contracts/test_architecture_migration_boundaries.py
```

并补充对应旧路径的 import 清零或 whitelist-only 证据，例如：

```bash
# 示例：确认主代码不再直接 import rs_core.rsagent，除被允许 facade 外
.venv/Scripts/python.exe - <<'PY'
# 使用本文档第 2 节 AST census 脚本，检查目标旧路径是否只剩 whitelist 项。
PY
```

---

## 7. Phase 1 结论

当前旧路径 import 状态已经可被量化、可被白名单约束、可作为后续 Phase 2-10 的退役基线。下一步不是直接删除旧目录，而是按 `RS_AGENT_COMPATIBILITY_BOUNDARY_STATUS.md` 的退役等级和本文 census 的调用点，逐条建立 parity test、替代入口和删除准入证据。
