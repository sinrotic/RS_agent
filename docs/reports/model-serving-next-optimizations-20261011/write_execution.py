"""按实际回滚结果生成报告，不把隔离收益或候选代码说成已经上线。"""
import json
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent


def load(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


live = load('production-original-live-state.json')
assert live['original_configuration_restored'] and not live['optimization_changes_promoted']
before, after = load('production_control-performance.json')['tests'], load('production_matched_after-performance.json')['tests']
table = []
for key in ['warm_tool_c1', 'warm_tool_c4', 'warm_tool_c8', 'warm_tool_c16', 'mixed_c4', 'mixed_c8', 'mixed_c16']:
    a, b = before[key]['summary'], after[key]['summary']
    table.append(f"| {key} | {a['e2e_median_ms']:.2f} | {b['e2e_median_ms']:.2f} | {a['e2e_p95_ms']:.2f} | {b['e2e_p95_ms']:.2f} |")
report = f'''# 模型服务优化实测、回滚与最终状态（2026-10-11）

本轮完成参数对照、候选实现和三次正式切换验收，**没有保留任何运行优化改动**。没有找到满足用户“原功能不能退化”的加速配置；正式服务已恢复此前 MLP INT4 / 注意力与 GDN BF16、50% 预算 / 128 序列上限，健康、源文件摘要与清理审计通过。不能将本轮称为模型速度优化已经成功。

## 当前正式服务

GPU 1 / `18082`，Qwen3.5-4B，对外 `qwen35-4b`，上下文 16384。96 个 MLP 投影使用 INT4；注意力、GDN 及其余原浮点模块保持原精度。模型路径、分词器、聊天模板、严格 Xgrammar、紧凑 JSON、完整视觉能力、前缀缓存、原两条真实前缀预热和 300 秒空闲保温保持此前部署。

模型加载 {live['model_loading_gib']:.2f} GiB，KV / 状态预算 {live['kv_cache_gib']:.2f} GiB / {live['kv_cache_tokens']} tokens，GPU 1 剩余 {live['gpu']['free_mib']} MiB。已核对当前安装版本 vLLM 0.24.0 的实际解析批次为 2048、async scheduling 与 chunked prefill 开启；没有改序列上限、注意力后端、KV dtype、生产副本数或入口协议。128 是调度上限，不代表 128 个满 16K 请求。

最终 API PID `{live['api_pid']}`、启动器 PID `{live['launcher_pid']}`；BGE PID 3417056 和既有 Agent 服务继续运行，GPU 0 训练没有修改。最终 `.env` SHA256 与四份启动/预热/探针脚本 SHA256，均与本轮开始时完全一致。[最终只读审计](production-original-live-state.json)

## 候选结果

| 候选 | 实测结果 | 最终处理 |
|---|---|---|
| token 批次 4096 / 8192 | 模型回归通过；混合请求平均耗时相对更快的一组前后基线约增加 2.3% / 4.7% | 未达到至少 8% 收益门槛，保留 2048 |
| MTP-1，现有部分量化 / 50% | KV tokens 106496 → 76725，约少 28%；固定规划未完成 2 → 3，RAG query 缺失 0 → 1；部分混合负载变慢 | 未通过功能、容量及性能门槛，不推广 |
| 预热前缀由两条扩为八条，随后执行探针 | 六条规划首次 1 token 中位数 603.15 → 601.34 ms | 未达到 5% 前缀响应收益门槛 |
| 八条前缀在探针后补回，含 16 路预热 | GPU 2 首次 1 token 603.15 → 297.28 ms；正式 GPU 1 mixed_c4 969.40 → 1772.26 ms、warm_tool_c16 2376.33 → 2987.02 ms | 正式稳态退化超过 20%，自动恢复 |
| 原两条前缀，仅增加 16 路及补回 | 功能回归通过；首次 16 路短工具突发 3026.60 → 3061.05 ms | 未达到至少 8% 首次突发收益，不启用 |
| 后台保温每条请求前检查负载，业务进入就停止本轮剩余预热 | 本地行为测试通过；正式性能、90 个模型请求、6 项内容属性、视觉、八条业务通过，但固定规划未完成 2 → 3 | 按功能门槛恢复；未上线 |
| 仅改保温模块，保持原 `.env` 与启动脚本 | 同顺序原版控制仍为 2/16，候选 3/16；schema 错误与 RAG 缺参均为 0 | 仍未通过固定规划门槛，再次恢复，停止推广 |

两次保温候选的日志均显示两条保温请求完成，没有记录“业务进入而跳过剩余前缀”。尚未确定多出未完成生成的原因，不能将其武断归因于跳过保温、量化精度、采样波动或某个新参数。源文件只改一项不等于已有证据证明实际输出不会退化；本轮依照结果恢复，没有放宽门槛。

MTP 小样本不能证明其普遍降低质量，但已足以拒绝本次全局推广。八条前缀的 1 token 改善只覆盖固定冷启动样本，不能称为完整回答或稳态吞吐同等提速；正式同卡复验避免只看该收益。

`prefix_baseline` 在前缀计时后因新增统计字段遗漏中止，未进入稳态选择；修复后的 `prefix_baseline2` 完成对照。失败状态与清理证据保留。九轮完成的 GPU 2 模型对照和一次中止轮均已关闭本次服务。[批次门槛](selection.json)、[前缀门槛](warmup-selection.json)、[16 路门槛](startup16-selection.json)

## 正式同顺序对照与未通过的保温候选

以下是恢复原版后执行相同测量、模型回归、视觉、八条业务、固定规划顺序的原版控制，与最后仅改保温模块的候选。最后候选已恢复，表中“候选”不是当前配置。

| 场景 | 原版中位数 ms | 候选中位数 ms | 原版 P95 ms | 候选 P95 ms |
|---|---:|---:|---:|---:|
{chr(10).join(table)}

固定 128 tokens 中位数 {before['decode128']['e2e_median_ms']:.2f} → {after['decode128']['e2e_median_ms']:.2f} ms。没有证实单次生成速度显著提高。闭环并发测量受请求到达时间、缓存状态和后台负载影响，不能将表中较低值直接归因于保温改动。

另有 24 请求、4 请求/秒的开放到达测量，记录实际发送滞后、完成吞吐、P95、token 用量及指标增量；未做持续容量、32 路或满 16K 并发 SLA 验收。首可见内容不是引擎 TTFT / ITL。早期正式基线采集时另一张卡正在隔离加载，主机 CPU 条件未完全控制；最终原版控制和仅改保温候选阶段已关闭隔离卡服务。

所有常规 JSON、工具和回答验收要求正常结束，未通过缩短业务生成预算制造加速；只有固定 128 tokens 测速允许 length 结束。性能中位数/P95 超过 20% 与规划指标增加均触发恢复。20% 是小规模试验保护阈值，不是允许真实业务固定变慢 20% 的承诺。[原版控制](production_control-performance.json)、[最后候选](production_matched_after-performance.json)

## 功能证据与候选代码

初版候选的本地相关测试 37 项通过；未通过正式验收后，将逐条检查保留为默认关闭的实验开关，当前本地相关测试 **39 项通过**。覆盖额外预热、补回失败不发布 ready、原探针保留、流式工具、真实前缀输入保留、保温遇业务中止及默认整轮检查行为保持。以下两项代码已保留供审阅，**当前服务器使用恢复的原代码**：

- `java_agent/deploy/remote/model/start_qwen35_4b_vllm.sh` 的可选额外形状预热，原 8 路探针保留，额外探针通过后补回真实前缀；任一阶段失败不得 ready。
- `java_agent/deploy/remote/model/vllm_prefix_warmup.py` 的逐条空闲检查，由 `VLLM_RECHECK_IDLE_PER_PREFIX` / `--recheck-idle-per-prefix` 控制，默认关闭。存在已发预热与新业务之间的竞态，不能保证零竞争；最后默认关闭版本未在服务器重新试验。

原版控制完成 90 个模型直连请求与 6 项内容属性、真实业务 8/8、工具失败数 0、视觉颜色 smoke 和固定规划 16 次；固定规划仍有原有 2 个未完成样本，schema 错误 0、RAG query 缺失 0。候选实际业务也各为 8/8，但固定规划未通过；不能把业务小样本通过称为全部语义完美。[原版规划](production_control-planning.json)、[最后候选规划](production_matched_after-planning.json)、[原版业务](production_control-business.json)

三次正式切换失败和自动恢复的记录均保留：[扩大前缀失败](production-deployment-state.json)、[保温组合失败](production-final-deployment-state.json)、[仅改保温失败](production-matched-deployment-state.json)。模板、温度、sampling seed 与冻结输入摘要逐条配对，没有改写 baseline 文件或忽略失败轮。

## 恢复与清理

三次切换均备份原 `.env` 与两份脚本，失败后仅停止本次 model process group，恢复原字节、重启并通过原 8 路严格输出探针，再更新此前 memory50 状态的当前 PID。现在 `/home/luo/RS_agent_java/model_deploy/partial-quantization-memory50-state.json` 是有效运行状态；本轮三份失败状态不是有效部署入口。

18092 / 18314 验证端口关闭、测试容器已移除、临时 accounts 与 clone 私有环境副本已删除。未使用的正式八条私有前缀文件已在核对身份和 SHA 后删除；原两条预热私有文件保持 0600。原 QA 账号文件和共享业务服务未删除，私有请求、凭据和原始日志未下载到仓库。历史备份与公开失败证据保留。

此前 50% / 128 的恢复入口已只读核验通过，默认不会改变配置：

```bash
python3 /home/luo/RS_agent_java/model_deploy/restore_qwen35_4b_partial_memory50.py
```

其 `--apply` 会恢复更早 40% / 64，**本轮没有执行**。本轮失败候选的恢复脚本因状态未 promoted，不能当当前配置入口。公开证据关联检查：`python docs/reports/model-serving-next-optimizations-20261011/verify_results.py`。资料与尚未执行的方向见 [研究记录](research.md)。
'''
(ROOT / 'execution.md').write_text(report, encoding='utf-8')
print('回滚执行记录已按最终原配置证据生成')
