# GPU 1 上的 Agent 并发压测报告

测试日期：2026-10-09。测试使用当前工作区构建的 Java Agent 和服务器上的本地 Qwen3.5-4B 权重。共发起 **3895 个真实 Agent SSE 轮次**，3878 个返回有效回答并正常结束；这些完成结果包含依赖降级，不能全部算作工具链健康成功。

## 结论

**短轮次场景最高验证通过的档位为 104 个同时发起的独立会话轮次**：312/312 完成，P95 28.157 秒，吞吐 3.633 完成轮次/秒。112 并发的 P95 为 30.298 秒，超过本次 30 秒门槛。可观察到的临界区约为 104～112；没有验证每一个整数档位，也没有寻找崩溃极限，不能把 104 当作物理硬上限。

104 档的工具审计中，309/312 没有 FAILED 工具记录，工具无失败率 **99.04%**；其余 3 次曾调用不可用的 RAG 接口，最终降级回答。96 档重复测试虽然 384/384 完成，但工具无失败率为 379/384＝98.70%。这说明轮次完成率和工具链健康率必须分开，不能据此承诺完整购物业务稳定支持 104 并发。

**默认并发额度只支持 8 个同时发起的短轮次请求稳定完成**。8 并发重复 320 次，全部完成，P95 5.778 秒；9 并发完成率 88.89%，12 并发完成率 66.67%。超过 8 路的请求约 0.21 秒就返回 SSE error，符合当前 8 路模型额度、200ms 等待超时的限制。这不是 GPU 的容量极限。

现有模型的 **4096 token 上下文与当前完整 Agent 提示/工具定义不兼容**：单请求即因上下文超限失败，减少到 256 输出 token 仍失败。本报告的有效并发数字全部以临时 **16384 token 上下文**为前提。

## 核心结果

| 配置与场景 | 并发 | 完成/请求 | 整轮 P95 | 完成轮次/秒 | 工具无失败率 |
|---|---:|---:|---:|---:|---:|
| 原模型 4K，单请求 | 1 | 0/1 | 无 | 0 | 未执行到模型工具调用阶段 |
| 16K，默认额度，重复验证 | 8 | 320/320 | 5.778 秒 | 1.450 | 该实例停止后内存 trace 已释放，未全量核验 |
| 16K，提高额度，重复验证 | 96 | 384/384 | 26.318 秒 | 3.623 | 98.70% |
| 16K，提高额度，独占临界复测 | 104 | 312/312 | 28.157 秒 | 3.633 | 99.04% |
| 16K，提高额度，独占临界复测 | 112 | 336/336 | 30.298 秒 | 3.640 | 98.21% |
| 16K，较大档位宏扫 | 192 | 576/576 | 49.006 秒 | 3.839 | 未全量核验 |

192 档说明请求仍可排队完成，但相对 104 档吞吐只增加约 5.7%，P95 增加约 74%。加大并发主要增加等待时间，不会等比例增加吞吐。并发数字包含 vLLM 内部排队，不代表同一瞬间有这么多路 GPU token 生成。

完整指标见 [metrics.md](metrics.md)，逐档 CSV 见 [summary.csv](summary.csv)。

## 环境与范围

- GPU：物理编号 **1**，NVIDIA GeForce RTX 4090，24564 MiB；CUDA_VISIBLE_DEVICES=1。GPU 0、2 已有训练任务，未调整或停止。
- 模型：本地 `/mnt/data/luo/models/Qwen3.5-4B`，服务名 `qwen35-4b`，vLLM 0.24.0，XGrammar，qwen3_xml 工具解析器，prefix caching 启用，thinking 禁用，温度 0，每次模型调用最多 1024 输出 token。
- Agent：当前工作区、Spring Boot 4.0.3、Java 21、虚拟线程；测试进程堆为 `-Xms256m -Xmx2g`。现有 Compose 默认 `-Xmx512m`，本次结果不能直接视为该容器资源配置的容量。
- JAR SHA256：`12f21aaabde344bf2d8484c88a21828951b4a84cc55d9735ee3c1e6a0e1f0677`。
- Git HEAD：`f3287905afafea322bd71f3e3ace5dfecb25dbe4`。工作区存在大量先前未提交修改，本次构建包含当前工作区状态，不能仅凭这个 HEAD 复现全部源码。
- 测试地址：部署服务器 loopback `127.0.0.1:18204`，模型为 `127.0.0.1:18082`。前端、网关鉴权、在线推荐、Redis、MySQL、Scylla 不在这次基准链路内。
- 会话与候选使用现有内存模式；固定候选是本地开发占位数据，不是真实在线召回。RAG 工具仍在 schema 中，其委派地址对应已停机的推荐服务。
- 单实例临界复测的 Agent RSS 峰值约 **1136 MiB**；模型独占时 GPU 显存约 **20261 MiB（19.8 GiB）**。资源约每 2 秒采样一次。

本次使用新会话测试初始轮次，未覆盖长会话上下文增长、持久化恢复、实际画像推荐、跨实例协调、小时级稳态或数据库容量。

## 提示词与方法

短轮次混合使用三种提示词：

1. 我想买一个日常通勤双肩包，但还没确定预算。请先问我一个最关键的澄清问题，暂时不要检索商品。
2. 选购通勤双肩包时，应该考虑哪些方面？请给出三条简短的一般建议，不推荐具体商品，不查询商品或用户历史。
3. 我每天背电脑通勤，想买双肩包，但不知道应该选多大。请先问我电脑尺寸，用一个简短问题回答，暂时不要检索商品。

每个请求使用独立 session_id；每批通过线程屏障同时发起，等待全部结束后再发下一批。宏扫一般每档 3 批，默认 8 档为 40 批，96 重复档为 4 批。96、104、112 的复测记录了 GPU 进程；独占临界复测还启用了 require-exclusive-gpu，一旦发现额外 GPU 进程就停止继续升档。

SSE 轮次完成要求：收到非空可见回答、没有 SSE error、收到 FINAL_ANSWER 结束事件；HTTP 200 自身不算成功。筛选门槛为完成率至少 99%、成功轮次 P95 ≤ 30 秒。延迟分位数只统计完成请求，失败率另列。工具审计读取同一测试会话的真实工具记录，不把存在 FAILED 工具的轮次算作工具链健康成功。

Agent 公共 SSE 在完整 answer_block 就绪后才展示内容，首可见回答耗时通常接近整轮耗时，不能将其等同于模型底层首 token 延迟。

## GPU 干扰与复测

宏扫的 128 档出现了额外显存占用；随后临界测试中确认 GPU 1 出现了其他用户进程，占用约 1 GiB。受干扰的 104、112 档 P95 分别为 40.659、42.041 秒，记录在 [boundary-shared.json](boundary-shared.json)，未用它们推断独占容量，没有停止该进程。

该进程结束后重新测试。独占复测结果保存在 [boundary-exclusive.json](boundary-exclusive.json)，GPU 进程采样峰值为 1；96 重复验证也只有模型进程，见 [raised-sustain.json](raised-sustain.json)。宏扫与共享样本保留作为环境干扰证据，不能与独占复测混合推导精确边界。

## 比较场景暴露的依赖问题

补充提示词：

> 请比较通勤双肩包的三种选择思路：轻量型、电脑保护型、防雨型。从重量、保护、收纳、舒适度、使用场景五个方面给出一般性的比较，最后给出简短选购建议。不推荐具体商品，不查询商品或用户历史，不编造价格。

8 并发 8/8 返回回答，P95 65.946 秒；单请求重复 3 次，3/3 返回回答，P95 59.791 秒。**这些不是正常长回答容量指标**：12 个比较轮次全部出现 `call_agent(rag_agent)` 工具失败，工具返回 `failed to call model provider`，随后 Agent 继续调用模型。单请求重复样本平均 5 次模型调用，8 并发样本平均 5.25 次。

代码确认 RAG 委派目标为 `http://rs-service-recommend:18103/agent/recommend/rag/support`，对应业务服务当前未运行。它仍被模型选择，说明仅有 Profile 授权检查不足以保证工具可执行；还需要依据依赖就绪状态治理工具暴露，并控制失败后的继续调用次数。

证据见 [comparison-tool-audit.json](comparison-tool-audit.json)、[comparison-repeat-tool-audit.json](comparison-repeat-tool-audit.json)、[comparison-trace-summary.json](comparison-trace-summary.json)。当前这些轮次最终回答成功的标志掩盖了工具失败；完整业务压测需要将降级状态单独统计。

## 后续容量验收起点

先将正式 Agent 与模型的上下文预算配齐，确认真实推荐/RAG接口就绪并避免向模型暴露不可用工具，再测真实候选、画像和持久化链路。基于本次短轮次延迟，16 并发 P95 7.659 秒、32 并发 P95 11.390 秒，可作为完整链路下一轮验收的起点；104 只适合作为本次条件下的临界观察值。

## 产物与复现

- [agent_capacity_probe.py](../../../java_agent/deploy/remote/app/agent_capacity_probe.py)：实际 SSE 请求、并发分档、GPU/模型监控、工具审计。只使用 Python 标准库。
- [agent_capacity_instance.py](../../../java_agent/deploy/remote/app/agent_capacity_instance.py)：独立测试实例的启动/停止，记录 JAR hash 和启动参数。
- [agent_capacity_model.py](../../../java_agent/deploy/remote/app/agent_capacity_model.py)：备份、临时调整并恢复已核验的 GPU 1 模型启动参数。
- [agent_capacity_report.py](../../../java_agent/deploy/remote/app/agent_capacity_report.py)：从原始 JSON 重新生成指标 Markdown 与 CSV。
- [build.log](build.log)：当前 JAR 构建成功记录；构建使用 -DskipTests，本次验证依赖真实请求与脚本语法检查，没有宣称运行完整单测套件。
- [boundary-tool-audit.json](boundary-tool-audit.json)：648 个临界轮次全部读取到 trace；104 档 3 个、112 档 6 个轮次出现工具失败。

在已经准备好同样的 16K 模型、测试 JAR 和测试实例的部署主机上，核心复现命令为：

```bash
python3 agent_capacity_probe.py --levels 1,2,4,6,8,9,12 --rounds 3 --output default-sweep.json
python3 agent_capacity_probe.py --levels 8 --rounds 40 --output default-sustain.json
# 将独立实例的模型/循环额度提高到 256，其他参数保持一致后：
python3 agent_capacity_probe.py --levels 104,112 --rounds 3 --require-exclusive-gpu --output boundary-exclusive.json
python3 agent_capacity_probe.py --audit-report boundary-exclusive.json --output boundary-tool-audit.json
```

工具审计必须在测试实例停止前进行；内存会话随实例退出释放。先前默认额度实例已经停止，因此其完成率不应冒充已全量核验的工具健康率。

本地从已有原始文件重新生成汇总：

```powershell
python -X utf8 java_agent/deploy/remote/app/agent_capacity_report.py docs/reports/agent-capacity-20261009
```

## 环境恢复

已停止测试 Agent，18204 端口关闭；模型仍在 GPU 1 上，恢复到原先 4096 上下文、0.85 显存利用率与 prefix keepalive 配置，重新通过原启动流程的结构化输出检查。没有修改原部署 JAR、业务配置、原模型脚本或其他 GPU 的训练任务。

恢复证据见 [restore-verification.json](restore-verification.json)。临时 16K 与提高并发额度没有留在业务部署中，因此报告中的 104 并发不能理解为当前正式配置已启用此容量。
