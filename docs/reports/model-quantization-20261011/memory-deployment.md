# INT4 显存优先部署（2026-10-11）

本文件记录前一版 INT4 / 50% 配置。最新已按用户授权部署 MLP INT4、注意力 / GDN BF16，并从 40% 扩容到 50% 预算 / 并发上限 128；当前状态及恢复入口见 [缓存扩容记录](../model-partial-quantization-20261011/cache-expansion.md)。以下数据为该历史部署的证据。

已部署 INT4，并将 vLLM 显存预算从 0.78 降到 0.50，正式服务健康、结构化输出探针通过。GPU 1 实测释放 6794 MiB，约 6.63 GiB；目前空闲 9215 MiB，约 9.00 GiB。

用户在速度优先对照结束后明确要求保留量化部署，优先腾出显存供其他任务使用。该次部署单独记录，正式切换结果以 `memory-deployment-state.json`、`memory-live-state.json` 为准；此前 `deployment-state.json` 的 BF16 回滚记录属于上一轮实验。

## 配置

- 模型：Intel Qwen3.5-4B INT4 AutoRound，固定 revision `0a857215cab37e8caa857a053005a73cf98ff2c4`。
- 目录：`/mnt/data/luo/models/Qwen3.5-4B-INT4-AutoRound-0a857215-rs-runtime`。保持原服务有效分词器、聊天模板和处理器资产，量化权重不变。
- 运行：GPU 1，正式端口 `18082`，对外模型名仍为 `qwen35-4b`。checkpoint 自动识别为 INC，实际使用 Marlin W4A16 / BF16 激活。
- `VLLM_GPU_MEMORY_UTILIZATION=0.50`，上下文仍为 16384，保留 XGrammar strict、prefix cache、紧凑 JSON、实际前缀预热和空闲保温。

降低显存预算是释放空间的关键，单独换量化权重可能只让 vLLM 为 KV / 状态缓存分配更多空间。该比例约束本 vLLM 实例，不自动为其他进程设置预算，也不保证所有时刻的占用严格等于该比例。[vLLM 0.24.0 显存预算文档](https://docs.vllm.ai/en/v0.24.0/api/vllm/config/cache/)

## 验证

隔离 GPU 2 的新配置启动探针全部通过，包含八路并发。完成 90 个模型直连请求和六个内容属性回归，其中真实最终回答 payload 回放留在远端私有文件中。模型加载为 3.73 GiB，KV 预算为 5.49 GiB，启动器报告 147024 个 KV tokens；16K 请求最大并发估算为 8.97，属于容量估计，不是八路长输入吞吐实测。隔离总显存使用 11783 MiB，固定 128 tokens 的中位耗时为 654.33 ms。

| 正式 GPU 1 对照 | 原 BF16 | 当前 INT4 / 50% 预算 |
|---|---:|---:|
| 模型加载显存 | 8.61 GiB | 3.73 GiB |
| 全卡显存使用（包含 BGE） | 21661 MiB | 14867 MiB |
| 全卡空闲显存 | 2421 MiB | 9215 MiB |
| 同长度 128 tokens 中位耗时 | 1299.77 ms | 656.80 ms |

正式模型进程约占 11760 MiB，同卡 BGE 为 3076 MiB，原 BGE PID 保持运行。全卡计数还包括其他 GPU 运行时开销，所以 3.73 GiB 仅是权重加载占用，不能把整套模型服务称为 4GB。固定生成耗时下降约 49.47%，这是模型直连微基准，不是完整业务加速承诺。

正式服务切换后再次执行同样的模型侧回归，再在本次独立 Java 实例执行三条推荐和一组两轮推荐，保留真实目录补全、公开投影和工具审计。业务检查保留失败记录；依据用户新优先级，不因单个完整业务耗时高于最初 BF16 小样本而撤回。模型无法正常启动、模型侧回归失败、业务样例全部失败或未释放预期显存时自动恢复 BF16。

正式启动七种结构化 / 工具探针与八路并发探针通过，再次完成 90 个模型直连请求和六个内容属性回归。五条真实业务均有最终回答、五件商品与完整目录补全，内部工具及回答属性检查为 4/5 通过：静音办公鼠标请求中一次 `rag_support` FAILED，但后续仍完成最终回答；编程键盘、本轮基础推荐及两轮推荐的内部工具检查通过。实际耗时依次为 3.66、22.56、16.25、1.82、8.62 秒。这一工具失败没有被重试成功或更改提示词掩盖。

完成状态见 `memory-answer-completion.json`，工具与耗时见 `memory-business.json`，模型直连结果见 `memory-production-model.json`。既有建议意图路由问题和这次 RAG 辅助失败仍需另行诊断；本次没有宣称业务无故障。

六个内容属性回归和五条实际业务都不构成所有语义、决策或负载的质量保证。此前同一 INT4 资产出现过一次 `rag_support` 失败；此前 BF16 复测也出现更多规划和生成 tokens，不能把业务变化全部归因于量化精度。既有一般建议意图路由问题未在本次任务修复，详见[此前对照](README.md)。

## 持久化与恢复

只修改正式 `.env` 的模型路径、量化选项、显存预算和独立缓存目录，原启动 / 预热 / 探针脚本摘要保持不变。原 `.env` 存在正式目录下的 `backup-quantization-memory-*` 私有备份目录。量化后的设置由现有启动入口读取，后续使用该入口重启会保持本配置。

服务器保留 `restore_qwen35_4b_memory50.py` 和 `quantization-memory50-state.json`。恢复脚本默认只检查当前部署的进程、配置和备份身份，不重启模型；显式 `--apply` 才恢复原 `.env` 并重启 BF16。它核对本次进程 PID 与进程组，服务另行重启导致 PID 变化时会拒绝动作，需要先更新身份记录。

```bash
python3 /home/luo/RS_agent_java/model_deploy/restore_qwen35_4b_memory50.py
# 需要恢复时才执行：
python3 /home/luo/RS_agent_java/model_deploy/restore_qwen35_4b_memory50.py --apply
```

已清理本次验收容器及凭据副本，隔离模型端口关闭，共享 Agent 保持运行，见 `memory-cleanup-state.json`。恢复脚本只读核验已实际执行通过，未再次恢复 BF16。原启动 / 预热 / 探针脚本摘要保持一致，正式配置写入 `.env`；保留旧模型和备份。没有停止共享前端、Gateway、Agent、BGE 或其他 GPU 的训练任务。
