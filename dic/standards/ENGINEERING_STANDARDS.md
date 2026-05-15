# 工程规范 v1

本文档定义当前阶段的最低工程规范，目标是让推荐 backbone、Agent、服务、前端和实验产物可维护、可验证、可复盘。

## 1. 目录职责

- `rs_core/`：核心源码，只放可复用业务逻辑和工程模块。
- `scripts/`：命令入口，只做参数解析与流程触发，不堆业务实现；统一使用 `main()` 和 `if __name__ == "__main__"` 入口保护。
- `configs/`：配置集中管理，避免把实验参数散落在代码里。
- `outputs/`：运行产物、日志、评估结果和临时报告，不放源码。
- `tests/`：测试代码，按 unit、smoke、slow、gpu、experiment、serving、frontend 等层级标记。
- `frontend/`：React Web Demo，只消费服务层和展示层 contract。
- `dic/`：当前说明文档、工程叙事和复盘材料。
- `old_dic/`：历史草稿归档，不作为当前规划依据。

## 2. 配置命名

- 可提交配置优先使用 `phase_X_Y_goal.yaml` 或 `hybrid_demo_*.yaml`。
- LOPO 相关配置文件名必须包含 `lopo`，便于区分普通评估和留一正样本评估。
- 临时搜索、网格调参或一次性实验配置必须命名为 `configs/**/_tmp_*.yaml`，且不得加入 git。
- 配置字段使用小写 snake_case；新增配置必须说明适用范围、输入数据、输出目录和关键阈值。
- 不把绝对路径、个人机器路径、密钥或临时调参值写入默认配置。
- 配置 contract 通过 `scripts/validate_engineering_contracts.py` 做轻量校验：tracked 配置必须可被项目 loader 读取，路径字段不得使用个人机器绝对路径，tracked 临时配置不得出现。

## 3. 实验产物

- 实验输出默认写入 `outputs/` 下的任务子目录。
- 产物目录应包含足够复现实验的配置、指标和必要日志。
- 一次性 smoke、tuning、临时对照、debug demo、verifier / verification 产物在验证结果并沉淀必要结论后应直接清理，避免污染主输出目录。
- 可用于复盘或面试叙事的关键结论，按需记录到 `dic/ENGINEERING_NARRATIVE_LOG.md`、`dic/OPTIMIZATION_NARRATIVE.md` 或 `dic/experiments/` 下的对应实验文档。

## 4. 测试层级

- `unit`：验证纯函数、小模块和边界条件，要求快速稳定。
- `smoke`：验证主链路能用小样本跑通。
- `slow`：耗时较长的离线流程或批量评估。
- `gpu`：依赖 GPU 的训练、召回或排序实验。
- `experiment`：实验性评估，不作为普通提交的默认门禁。
- `serving`：服务 API、session、chat、feedback 等接口验证。
- `frontend`：前端构建、类型检查或端到端演示相关验证。
- 所有 `tests/test_*.py` 必须声明文件级 `pytestmark`；普通 CI 通过 `scripts/select_tests_by_marker.py --marker unit --marker smoke` 自动选择快速门禁测试，避免维护测试文件白名单。
- v1.3 开始允许组合 marker：服务冒烟可同时标记 `serving + smoke`，服务运行时单测可标记 `unit + serving`，GPU 训练实验标记 `experiment + gpu`，长耗时离线实验标记 `experiment + slow`。默认 CI 仍只跑 `unit or smoke`，serving 作为专项门禁单独选择；`gpu`、`slow`、`experiment` 不进入默认门禁。

## 5. 日志与异常

- 脚本入口应输出关键输入、输出路径、样本规模和核心指标。
- 模块内部优先返回结构化结果，少用裸 `print`。
- 异常信息要说明失败对象和关键上下文，不吞异常。
- 对外部输入、文件路径、模型输出和 API 请求做边界校验；内部可信调用不堆防御式样板。

## 6. 新代码规则

- 先放到职责匹配的目录，不把核心逻辑写进脚本或 notebook。
- 新增公共能力优先复用 `rs_core/` 已有结构。
- 不新增与当前阶段无关的大抽象、兼容层或功能开关。
- 不修改召回、排序、Agent、服务或前端 contract 时，不顺手改业务逻辑。
- 文档、命令和过程日志默认使用中文；代码标识符、配置项和模型名保持原文。

## 7. 本地命令

在 Windows 本地默认使用项目虚拟环境：

```bash
./.venv/Scripts/python.exe -m pytest -m unit
./.venv/Scripts/python.exe -m pytest -m smoke
./.venv/Scripts/python.exe -m ruff check rs_core
./.venv/Scripts/python.exe scripts/validate_engineering_contracts.py
```

前端命令从项目根目录执行：

```bash
npm --prefix frontend ci
npm --prefix frontend run lint
npm --prefix frontend run build
```

GPU、slow、experiment 标记默认不进入快速本地验证，按任务需要显式运行。

## 8. CI v1

- CI v1 只做最低工程门禁：Python 依赖安装、ruff、unit/smoke 测试。
- CI v1 不跑 GPU、slow、experiment 或完整前端 E2E。
- CI v1 不发布包、不部署服务、不上传实验产物。
- 后续如果服务和前端进入稳定演示阶段，再扩展 serving/frontend 专项门禁。

## 9. 非目标

- 当前规范不是生产级 MLOps、在线 AB 实验或全量 CI/CD 方案。
- 不要求所有历史脚本一次性迁移。
- 不要求前端达到生产级质量。
- 不把 `old_dic/` 历史材料重新纳入当前工程计划。
- 不用规范文档替代实际测试、评估指标或可复现实验产物。
