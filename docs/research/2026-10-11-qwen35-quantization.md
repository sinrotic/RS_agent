# Qwen3.5-4B 在现有 RTX 4090 服务上的量化路线

调查日期：2026-10-11。本文给出兼容性依据和实验顺序，不表示候选已部署或已获得加速。当前实装 vLLM 版本字符串为 `0.24.0`，`_version.py` 的 commit 字段为 `gee0da84ab`；同时直接只读检查服务器安装的源码。版本标签与源码演进可能存在差异，选择内核须以当前安装代码和启动日志为准。

## 可以立即试验的路线

先在隔离 GPU 上复测**中间第 8～23 层 MLP 的 FP8 权重、BF16 激活，即 W8A16 Marlin**。使用当前原始权重，无需下载另一个模型，也无需离线校准。它比整个模型 INT4 的改动范围小，且本项目已有对照和业务验收脚本。此前正式重启验收失败，所以这次需要重新覆盖冷启动、热缓存和重启；旧隔离结果不能直接作为部署依据。[项目旧验收报告](../reports/agent-quantization-20261009/README.md)

在线配置仍使用当前已实现的 JSON 接口：

```bash
VLLM_QUANTIZATION=fp8_per_block
VLLM_TEST_FORCE_FP8_MARLIN=1
VLLM_QUANTIZATION_CONFIG='{"ignore":["lm_head","re:.*visual.*","re:.*linear_attn.*","re:.*self_attn.*","re:.*layers\\.(?:0|1|2|3|4|5|6|7|24|25|26|27|28|29|30|31)\\..*"]}'
```

`fp8_per_block` 对原始 FP16/BF16 权重在加载时量化。在线 `ignore` 接受完整名称或 `re:` 正则，普通字符串不自动按子串匹配。融合投影的所有分片必须采用一致精度。当前在线实现拒绝显式 `activation` override，不能凭空设置一个 BF16 激活字段。[在线配置源码](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/config/quantization.py)、[在线分派源码](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/model_executor/layers/quantization/online/base.py)、[忽略规则源码](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/model_executor/layers/quantization/compressed_tensors/utils.py)

当前 Marlin FP8 实装代码在 SM89 上要求 `VLLM_TEST_FORCE_FP8_MARLIN=1`；这是当前版本的测试开关。实际内核走权重量化路径，无默认激活量化。启动后必须看到 Marlin 内核证据，再把它称作 W8A16，不能仅依据 `fp8_per_block` 名称判定。[Marlin FP8 源码](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/model_executor/kernels/linear/scaled_mm/marlin.py)

若此保守配置没有可重复的速度优势，下一候选是 **Intel 发布的 Qwen3.5-4B INT4 AutoRound**。它保留 BF16 激活、对称 4 bit 权重、group size 128，使用 GPTQ 打包；不需要在推理环境安装 AutoRound 或重新校准。它是 Intel 对 Qwen 原模型的量化发布，并非 Qwen 官方量化权重。模型卡明确给出 BF16 的 vLLM 启动方法。[Intel 模型卡](https://huggingface.co/Intel/Qwen3.5-4B-int4-AutoRound)、[配置文件](https://huggingface.co/Intel/Qwen3.5-4B-int4-AutoRound/blob/main/config.json)

## INT4 候选的固定下载信息

- 仓库：`Intel/Qwen3.5-4B-int4-AutoRound`
- 固定 revision：`0a857215cab37e8caa857a053005a73cf98ff2c4`
- 全部文件：`4,603,623,641` bytes，约 4.60 GB。
- 五个 safetensors 分片：`4,583,501,352` bytes，约 4.27 GiB；该数字包含分片头，与索引中 tensor 数据的 `4,583,300,608` bytes 略有差异。
- 当前服务 venv 已安装 `huggingface-hub 1.22.0`、`safetensors 0.8.0`、`transformers 5.13.0`；未安装 AutoRound、llmcompressor、GPTQModel。

revision 和全量字节数由 Hugging Face 模型 API 只读查询；索引及发布文件树可复核权重分片。这里是磁盘大小，不是服务总显存承诺。[发布文件树](https://huggingface.co/Intel/Qwen3.5-4B-int4-AutoRound/tree/0a857215cab37e8caa857a053005a73cf98ff2c4)、[权重索引](https://huggingface.co/Intel/Qwen3.5-4B-int4-AutoRound/blob/0a857215cab37e8caa857a053005a73cf98ff2c4/model.safetensors.index.json)

以下只是下载方案；本调查没有执行下载：

```python
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="Intel/Qwen3.5-4B-int4-AutoRound",
    revision="0a857215cab37e8caa857a053005a73cf98ff2c4",
    local_dir="/mnt/data/luo/models/Qwen3.5-4B-int4-AutoRound-0a857215",
    allow_patterns=["*.json", "*.safetensors", "*.jinja"],
    max_workers=2,
)
```

应在独立模型目录运行，保持原 BF16 文件完整。量化加载参数用 checkpoint 的配置自动识别，清空在线 `VLLM_QUANTIZATION_CONFIG`。当前 INC 后端会识别 `quant_method=auto-round`，支持 `auto_round:auto_gptq` 打包、BF16 激活和 Marlin 推理。[INC 配置源码](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/model_executor/layers/quantization/inc/inc.py)

## Gated DeltaNet、排除层与 BF16 的边界

GDN 并非完全不能量化。安装源码中的限制注释针对 `in_proj_ba` 的 blockwise FP8；其创建函数仍传递量化配置。对 AutoAWQ、AutoGPTQ 和 INC，代码还会复制 b/a 投影，以满足 Marlin 的最小输出宽度并处理张量并行限制。因此源码支持 INT4 GDN 投影路径，但最终加载与质量仍须在本机验证。[GDN 源码](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/model_executor/layers/mamba/gdn/qwen_gdn_linear_attn.py)

Intel 候选索引包含 GDN 的 qkv、z、b、a、out 投影的 `qweight/qzeros/scales`，MLP 和普通注意力也量化；视觉模块和 GDN 卷积、归一化及状态参数保留浮点。它比“只量化中间 MLP”的范围大，旧方案保留 GDN 的质量结论不能套用。[候选 tensor 索引](https://huggingface.co/Intel/Qwen3.5-4B-int4-AutoRound/blob/0a857215cab37e8caa857a053005a73cf98ff2c4/model.safetensors.index.json)

| 格式 | 当前实现的排除机制 | 注意事项 |
|---|---|---|
| 在线 FP8 | `quantization_config.ignore`，完整名称或 `re:` 正则 | 只能用于在线配置，保留原 BF16 权重 |
| AWQ | checkpoint `modules_to_not_convert` | 当前 AutoAWQ 接受 BF16；要确认实际选择 Marlin，避免回退未优化内核 |
| GPTQ | checkpoint `dynamic` 的 `-:` 排除，或 `modules_in_block_to_quantize` | 融合投影所有分片精度一致 |
| AutoRound / INC | checkpoint `extra_config` 与 block 列表 | 需和实际已导出的 tensor 精度一致 |

以上机制依据当前实现。给已量化 checkpoint 临时添加排除配置，并不会重新产生对应 BF16 tensor，不能借此“恢复”敏感层；保留敏感层需要在离线导出时就保留原权重。[AutoAWQ 源码](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/model_executor/layers/quantization/auto_awq.py)、[GPTQ 排除与融合检查](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/model_executor/layers/quantization/utils/gptq_utils.py)、[INC 配置解析](https://raw.githubusercontent.com/vllm-project/vllm/ee0da84ab/vllm/model_executor/layers/quantization/inc/config_parser.py)

## 若需要对我们自己的权重做 INT4

AWQ/GPTQ/AutoRound 的正常离线量化需要校准或权重优化，并导出独立 checkpoint；单纯给原始 BF16 模型添加 `--quantization awq` 或 `gptq` 不会完成量化。AutoRound 支持本地模型、本地 JSON 校准集、不同层精度以及 AWQ/GPTQ 打包。标准优化使用校准样本；RTN 是另一种免校准近似路径，应作为独立候选，不能假定与完整 AutoRound 质量相同。[AutoRound 使用指南](https://github.com/intel/auto-round/blob/main/docs/step_by_step.md)

在独立远端环境做导出，避免变更当前推理 venv。校准样本覆盖中文商品约束、工具选择、JSON 参数、明确无需检索的完整建议，并预留未参与校准的验收样本。保留 embedding、视觉、输出层以及敏感 GDN 投影，先枚举实际模块名称再生成 layer config；融合投影保持一致精度。这里的取舍属于针对旧回归证据的实验建议，不能保证量化不影响质量。

## 验收要求

同一提示词、工具、温度、输出上限和上下文，与 BF16 配对比较。至少检查结构化探针、实际工具无失败、三条建议等回答完整性、多个候选商品的事实及 ID 合法性；同时覆盖单请求、并发、冷启动和重启后的热缓存。不能只测短 JSON，也不能把输出变短、工具轮次变化的速度收益全部归因于量化内核。

按生成 token 数量和语义完整性解释首 token、逐 token、总耗时与吞吐结果。实际权重占用和 KV 预留分别记录：即使权重减少，vLLM 仍可能按显存预算预留更多缓存，总显存不会自动降到 4GB。只有重启后仍通过业务检查、且速度改善可重复，才进入正式服务；否则恢复 BF16。

以上是最初速度优先目标的验收要求。用户之后明确改为部署量化、优先腾出显存；实际已部署保持原分词器的 INT4 与 50% 显存预算，释放约 6.63 GiB，模型侧回归通过。五条业务有最终回答，其中一条 RAG 辅助工具失败，未因旧时延门槛撤回。该部署依据新的用户要求，不能表述为满足原来的业务加速要求，见[显存优先部署记录](../reports/model-quantization-20261011/memory-deployment.md)。
