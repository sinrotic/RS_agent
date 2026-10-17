# Agent 并发实测指标汇总

日期：2026-10-09。只统计实际请求结果，HTTP 200 不等于成功。

通过条件：有非空可见回答、无 SSE error、以 FINAL_ANSWER 结束；该档成功率至少 99%，成功轮次 P95 ≤ 30 秒。
延迟分位数仅基于成功请求；失败率独立列出，不能用失败的快速返回提高吞吐指标。吞吐为成功轮次/整档墙钟时间。

轮次完成不代表所有工具成功。已审计档位另列工具无失败率，分母为该档全部请求；未审计档位标为未核验。工具记录中的初始 recommend_candidates 在本次测试中来自固定候选，不是在线召回。

范围：当前 Java Agent + GPU 1 上本地 Qwen3.5-4B；内存会话与固定候选；不包含网关、真实推荐、Redis、MySQL、Scylla。每次请求使用新会话；重复轮次以屏障同时发起，等待该批全部结束再发下一批。

## 每档结果

| 原始文件 | 并发 | 完成/总数 | 完成率 | P50 秒 | P95 秒 | P99 秒 | 首回答 P95 秒 | 完成轮次/秒 | SSE/延迟通过 | 工具无失败率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| [boundary-exclusive.json](boundary-exclusive.json) | 104 | 312/312 | 100.0% | 18.462 | 28.157 | 28.326 | 28.156 | 3.633 | 是 | 99.04% |
| [boundary-exclusive.json](boundary-exclusive.json) | 112 | 336/336 | 100.0% | 18.602 | 30.298 | 30.765 | 30.297 | 3.64 | 否 | 98.21% |
| [boundary-shared.json](boundary-shared.json) | 104 | 312/312 | 100.0% | 27.334 | 40.659 | 41.081 | 40.658 | 2.537 | 否 | 未核验 |
| [boundary-shared.json](boundary-shared.json) | 112 | 336/336 | 100.0% | 22.755 | 42.041 | 42.335 | 42.041 | 3.186 | 否 | 未核验 |
| [comparison-repeat.json](comparison-repeat.json) | 1 | 3/3 | 100.0% | 38.843 | 59.791 | 59.791 | 59.79 | 0.025 | 否 | 0.0% |
| [comparison-sweep.json](comparison-sweep.json) | 1 | 1/1 | 100.0% | 27.947 | 27.947 | 27.947 | 27.946 | 0.036 | 是 | 0.0% |
| [comparison-sweep.json](comparison-sweep.json) | 8 | 8/8 | 100.0% | 53.859 | 65.946 | 65.946 | 65.946 | 0.121 | 否 | 0.0% |
| [default-sustain.json](default-sustain.json) | 8 | 320/320 | 100.0% | 2.567 | 5.778 | 5.865 | 5.777 | 1.45 | 是 | 未核验 |
| [default-sweep.json](default-sweep.json) | 1 | 3/3 | 100.0% | 1.053 | 4.118 | 4.118 | 4.116 | 0.49 | 是 | 未核验 |
| [default-sweep.json](default-sweep.json) | 2 | 6/6 | 100.0% | 1.326 | 5.992 | 5.992 | 5.989 | 0.511 | 是 | 未核验 |
| [default-sweep.json](default-sweep.json) | 4 | 12/12 | 100.0% | 1.723 | 4.757 | 4.757 | 4.755 | 0.855 | 是 | 未核验 |
| [default-sweep.json](default-sweep.json) | 6 | 18/18 | 100.0% | 1.945 | 5.57 | 5.57 | 5.568 | 1.156 | 是 | 未核验 |
| [default-sweep.json](default-sweep.json) | 8 | 24/24 | 100.0% | 2.168 | 5.629 | 5.648 | 5.627 | 1.501 | 是 | 未核验 |
| [default-sweep.json](default-sweep.json) | 9 | 24/27 | 88.89% | 2.221 | 5.497 | 5.549 | 5.496 | 1.507 | 否 | 未核验 |
| [default-sweep.json](default-sweep.json) | 12 | 24/36 | 66.67% | 2.32 | 5.85 | 5.85 | 5.848 | 1.442 | 否 | 未核验 |
| [original-4k-1024.json](original-4k-1024.json) | 1 | 0/1 | 0.0% | None | None | None | None | 0.0 | 否 | 未核验 |
| [original-4k-256.json](original-4k-256.json) | 1 | 0/1 | 0.0% | None | None | None | None | 0.0 | 否 | 未核验 |
| [raised-sustain.json](raised-sustain.json) | 96 | 384/384 | 100.0% | 17.929 | 26.318 | 26.687 | 26.317 | 3.623 | 是 | 98.7% |
| [raised-sweep.json](raised-sweep.json) | 8 | 24/24 | 100.0% | 3.356 | 6.614 | 6.881 | 6.611 | 1.319 | 是 | 未核验 |
| [raised-sweep.json](raised-sweep.json) | 16 | 48/48 | 100.0% | 3.638 | 7.659 | 7.733 | 7.658 | 2.257 | 是 | 未核验 |
| [raised-sweep.json](raised-sweep.json) | 32 | 96/96 | 100.0% | 6.519 | 11.39 | 11.48 | 11.39 | 2.905 | 是 | 未核验 |
| [raised-sweep.json](raised-sweep.json) | 48 | 144/144 | 100.0% | 9.661 | 15.189 | 15.318 | 15.188 | 3.182 | 是 | 未核验 |
| [raised-sweep.json](raised-sweep.json) | 64 | 192/192 | 100.0% | 12.812 | 19.859 | 20.399 | 19.858 | 3.135 | 是 | 未核验 |
| [raised-sweep.json](raised-sweep.json) | 96 | 288/288 | 100.0% | 17.726 | 26.505 | 26.723 | 26.505 | 3.615 | 是 | 未核验 |
| [raised-sweep.json](raised-sweep.json) | 128 | 384/384 | 100.0% | 20.533 | 36.586 | 37.279 | 36.585 | 3.642 | 否 | 未核验 |
| [raised-sweep.json](raised-sweep.json) | 192 | 576/576 | 100.0% | 27.67 | 49.006 | 49.482 | 49.005 | 3.839 | 否 | 未核验 |
| [smoke-16k.json](smoke-16k.json) | 1 | 3/3 | 100.0% | 3.04 | 4.459 | 4.459 | 4.457 | 0.353 | 是 | 未核验 |

## 资源采样

每约 2 秒采样一次，峰值可能漏过更短的瞬时变化。

| 原始文件 | GPU 显存峰值 MiB | GPU 利用率均值 % | GPU 温度峰值 ℃ | Agent RSS 峰值 MiB | 模型执行峰值 | 模型排队峰值 |
|---|---:|---:|---:|---:|---:|---:|
| boundary-exclusive.json | 20261 | 88.5 | 81 | 1136.02 | 90.0 | 76.0 |
| boundary-shared.json | 21277 | 96.0 | 82 | 1106.63 | 88.0 | 85.0 |
| comparison-repeat.json | 20261 | 80.9 | 70 | 1135.73 | 1.0 | 0.0 |
| comparison-sweep.json | 20261 | 90.8 | 74 | 1127.15 | 8.0 | 1.0 |
| default-sustain.json | 20259 | 93.3 | 76 | 658.11 | 8.0 | 4.0 |
| default-sweep.json | 20259 | 79.0 | 74 | 633.28 | 8.0 | 0.0 |
| original-4k-1024.json | 20257 | 0.0 | 46 | 586.42 | 0.0 | 0.0 |
| original-4k-256.json | 20257 | 0.0 | 46 | 556.92 | 0.0 | 0.0 |
| raised-sustain.json | 20261 | 88.1 | 80 | 1116.57 | 87.0 | 75.0 |
| raised-sweep.json | 21237 | 88.4 | 81 | 1006.69 | 91.0 | 149.0 |
| smoke-16k.json | 20259 | 34.5 | 61 | 542.21 | 1.0 | 0.0 |

## 判读限制

- 单档筛选只有少量批次；稳定性结论应优先查看 sustain 文件。没有进行小时级稳态、长会话、故障恢复或在线推荐容量验证。
- 测试使用温度 0、最多 1024 输出 token、prefix caching、strict 工具参数与禁用 thinking；真实输入长度、工具链和生成长度改变后，容量会变化。
- 首可见回答通常是完整 answer_block，不能等同于底层模型的首 token 延迟。
- 原模型上下文为 4096；兼容测试临时改为 16384。原配置失败和调整后的容量必须分开解释。
- 最后一档通过只能给出已测下界；某档失败也不能证明更高所有档位都失败。临界附近需要重复验证。

- boundary-shared.json 包含已确认的其他 GPU 进程干扰；raised-sweep.json 的 128 档出现额外显存占用。这些数据不能直接与独占复测混合推断容量。
- comparison 文件全部出现 RAG 委派工具失败，耗时包含失败后的继续生成，属于依赖降级样本，不是正常长回答容量。
