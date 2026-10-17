# 七条购物请求：原始提取、争议与修订草案

本次仅离线整理原有 7 条顾客原话；新增请求 0 条，新增模型调用 0 次，未入正式评测集，未上线。
原始 8 个槽位包括一次生成 JSON 失败，不补造第 8 条。所有原始隔离状态保持不变。

修订草案由 Codex 根据已有原话拟订，不是 6-luna 的重新提取，更不是已批准的标准答案。
结构及逐字证据校验通过，不等于语义正确。原审核仍是同一模型的判断，存在相关误差。

## 新协议的边界

先判断推荐、比较、兼容咨询或方法咨询，再记录当前条件；近似条件不造容差、不变成硬过滤。
明确要回答的比较维度和核对方法单独放 answer_requirements。背景设备和备选方案不自动变成必购商品。
unknowns 区分当前答案必需、具体商品判断才必需、可选优化。一般解释可先回答，但未知时不能保证具体兼容性。
本人历史仅是经授权的弱偏好，不能覆盖当前需求，不能迁移给收礼人，也不能证明现有设备。

| 样本 | 修订意图 | 首要问题 |
| --- | --- | --- |
| synth-000-00 无线适配器：近似预算不是硬上限 | recommendation | 三十左右被改成价格不超过30 |
| synth-000-01 无线适配器：安装便利、可靠性与可选追问 | recommendation | 添个是否严格限定购买数量存在解释空间 |
| synth-001-01 送朋友通勤耳机：收礼人需求独立于赠送者画像 | recommendation | 一副描述购买单位，不限定只展示一个推荐 |
| synth-002-00 显卡水冷：核对方法不是强制购买安装架 | compatibility_consultation | 提到安装架被升格为必须购买安装架 |
| synth-002-01 显卡散热：比较维度和核查步骤不能漏提 | mixed | 仅提未知型号，遗漏明确的方案比较与方法咨询 |
| synth-003-00 网线与接头：原提取缺失，修订只是草案 | mixed | 提取失败且原响应未保存，不能展示为原模型提取 |
| synth-003-01 网线方案选择：近似长度与先解释后追问 | mixed | 大概50英尺被写成字符串精确等值条件 |

## 1. 无线适配器：近似预算不是硬上限（synth-000-00）

顾客原话：

> 家里台式机的无线网卡不太稳定，想换个USB Wi‑Fi适配器，最好支持双频。主要是Windows 11用，预算三十左右，有合适的吗？

### 原始提取与审核

原始包保存已验证提取；不声称恢复完整原响应

原始状态 `quarantined`；失败阶段 `audit`。

```json
{
  "hard_constraints": [
    {
      "field": "product_type",
      "op": "eq",
      "value": "USB Wi‑Fi适配器",
      "quote": "想换个USB Wi‑Fi适配器"
    },
    {
      "field": "operating_system",
      "op": "eq",
      "value": "Windows 11",
      "quote": "主要是Windows 11用"
    },
    {
      "field": "price",
      "op": "lte",
      "value": 30,
      "quote": "预算三十左右"
    }
  ],
  "soft_preferences": [
    {
      "need": "支持双频",
      "quote": "最好支持双频"
    }
  ],
  "unknowns": [
    {
      "slot": "currency",
      "reason": "原话未说明预算使用的币种。"
    },
    {
      "slot": "purchase_for",
      "reason": "提到家里的台式机，但未说明购买者是本人还是他人。"
    }
  ],
  "purchase_for": "unknown",
  "purchase_for_quote": null,
  "needs_clarification": false,
  "clarification_questions": []
}
```

审核来源：previous_supplemental_diagnostic_call；这是已存在的输出，不是本次调用。
模型维度判断：naturalness=pass；extraction_fidelity=fail；fact_boundary=pass；clarification_policy=pass。

- naturalness：顾客用语像正常的购物询问：说明设备问题、目标产品、主要系统、预算和一项偏好。
- extraction_fidelity：产品类型、Windows 11 和双频偏好有原话支持；但把“预算三十左右”抽成硬性不超过 30（lte）过强。“左右”表达近似预算，并未明确绝不超过 30。purchase_for 标为 unknown 也过度谨慎：“家里台式机”没有说明购买者身份，但这不影响本人需求提取，且不应把购买者身份当作当前待澄清槽位。
- fact_boundary：目录中有一款标价 26.99、标题注明双频并支持 Windows 10/11 的 USB Wi‑Fi 适配器；但价格币种未确认，不能据此断言符合顾客实际币种下的预算。历史记录是过去的正向评价，不足以推断当前偏好，也不能补足预算币种。
- clarification_policy：无需先澄清即可继续检索或给出带条件的结果。若价格是否必须严格不超过 30 会影响筛选，可以说明币种未确认并询问；但这不是开始回应前的必要澄清。

当前只读兼容检查：通过；四维理由对象已被旧格式兼容器接受，原状态不翻转。

### 争议与修订建议

- 三十左右被改成价格不超过30（明确的结构或语义问题）。证据：『预算三十左右』。建议：改为approximate/about/30，币种null；不造上下浮动范围，暂不计算预算命中。
- 家用设备不能直接证明购买对象，但对象未知不必追问（解释性争议，待人审）。证据：『家里台式机』。建议：保留recipient=unknown；仅在确认适用本人且画像已授权时弱参考历史，不用询问身份来阻塞推荐。

### 修订草案如何使用

请求动作：recommend。

| 强度 | 条件 | 运算和值 | 单位 |
| --- | --- | --- | --- |
| strict | product_type | eq USB Wi-Fi适配器 | 未明确 |
| strict | operating_system | eq Windows 11 | 未明确 |
| approximate | price | about 30 | 未明确 |
| preference | dual_band | prefer True | 未明确 |

明确要回答：给出适合Windows 11的USB Wi-Fi适配器参考，交代已知和待确认条件。

澄清模式：`not_needed`；可先回答：True。

- 未知 `currency`：optional_refinement；用于 recommend。币种未知不能据目录原始标价认定符合实际预算；可先给带条件参考

建议追问：

不设置必须追问；不为了补齐槽位盘问顾客。

画像参与：`weak_reference_if_self`。

- 当前双频倾向优先于不相干历史；不要求顾客说出画像触发词。
- 不把26.99原始价格单位直接与顾客的30作同币种比较，不声称用户设备一定适配。
- 近似预算尚无人工校准容差，只检查是否忠实表达，不能据此造价格满分或扣分。

修订状态：待人审；协议校验通过 ≠ 标准答案批准。完整新结构和审核原输出见同目录 review.json。

## 2. 无线适配器：安装便利、可靠性与可选追问（synth-000-01）

顾客原话：

> 家里有台台式机放在路由器旁边不太方便拉网线，最近无线连接也不太稳定，想添个 USB 网络适配器改善一下。比起追求特别高的速度，我更在意安装别太折腾、日常用着可靠；电脑是 Windows，但具体接口和兼容要求我还得确认。能帮我看看哪种更合适吗？

### 原始提取与审核

原始包保存已验证提取；不声称恢复完整原响应

原始状态 `quarantined`；失败阶段 `audit`。

```json
{
  "hard_constraints": [
    {
      "field": "product_type",
      "op": "eq",
      "value": "USB 网络适配器",
      "quote": "想添个 USB 网络适配器"
    },
    {
      "field": "operating_system",
      "op": "eq",
      "value": "Windows",
      "quote": "电脑是 Windows"
    },
    {
      "field": "quantity",
      "op": "eq",
      "value": 1,
      "quote": "想添个 USB 网络适配器"
    }
  ],
  "soft_preferences": [
    {
      "need": "安装别太折腾",
      "quote": "我更在意安装别太折腾"
    },
    {
      "need": "日常使用可靠",
      "quote": "日常用着可靠"
    },
    {
      "need": "不以追求特别高的速度为优先",
      "quote": "比起追求特别高的速度"
    }
  ],
  "unknowns": [
    {
      "slot": "电脑的具体接口",
      "reason": "顾客表示具体接口还需确认。"
    },
    {
      "slot": "适配器兼容要求",
      "reason": "顾客表示兼容要求还需确认。"
    }
  ],
  "purchase_for": "unknown",
  "purchase_for_quote": null,
  "needs_clarification": true,
  "clarification_questions": [
    {
      "question": "电脑有哪些可用的 USB 接口？",
      "slot": "电脑的具体接口",
      "reason": "需要确认接口，才能判断适配器是否能连接。"
    },
    {
      "question": "你的 Windows 版本或其他兼容要求是什么？",
      "slot": "适配器兼容要求",
      "reason": "需要确认具体兼容要求，避免推荐不兼容的适配器。"
    }
  ]
}
```

审核来源：previous_supplemental_diagnostic_call；这是已存在的输出，不是本次调用。
模型维度判断：naturalness=pass；extraction_fidelity=fail；fact_boundary=pass；clarification_policy=pass。

- naturalness：顾客表达自然、连贯，说明了使用场景、主要顾虑和待确认信息，没有明显不合常理之处。
- extraction_fidelity：提取保留了产品类型、Windows、安装便利和可靠性等要点，也标出了接口与兼容信息未知；但把“想添个 USB 网络适配器”推成硬性数量恰为 1 缺少依据。顾客没有明确说只买一个。速度偏好也应理解为不优先追求极高速度，而不是不需要较高速度。
- fact_boundary：提取没有用历史评价推断顾客对网络适配器的偏好，也没有把目录商品的标题信息当作顾客要求。目录只列出有限商品，不能据此断言全站无其他选择或某商品实际可用。
- clarification_policy：询问可用 USB 接口和 Windows 版本或兼容要求，与顾客明确表示尚待确认的信息相关。当前信息不足以判断具体接口和兼容性，保留为未知并澄清是合理的。

当前只读兼容检查：通过；四维理由对象已被旧格式兼容器接受，原状态不翻转。

### 争议与修订建议

- 添个是否严格限定购买数量存在解释空间（解释性争议，待人审）。证据：『想添个 USB 网络适配器改善一下』。建议：暂不设严格数量；即使人审认可买一个，也只影响purchase_quantity，不限定recommendation_count。
- 接口未知限制具体兼容结论，不应阻塞一般选择建议（明确的结构或语义问题）。证据：『具体接口和兼容要求我还得确认』。建议：先说明按安装便利和可靠性选择的方向，再合并追问USB接口与Windows版本；不知道时不保证具体型号兼容。
- 不追求最高速不等于拒绝高速产品（明确的结构或语义问题）。证据：『比起追求特别高的速度，我更在意安装别太折腾、日常用着可靠』。建议：保留可靠和便利的相对优先级；不添加网速硬上限或任意数字权重。

### 修订草案如何使用

请求动作：recommend。

| 强度 | 条件 | 运算和值 | 单位 |
| --- | --- | --- | --- |
| strict | product_type | eq USB网络适配器 | 未明确 |
| strict | operating_system | eq Windows | 未明确 |
| preference | installation_difficulty | minimize 安装便利 | 未明确 |
| preference | reliability | prefer 日常可靠性优先于极高速度 | 未明确 |

明确要回答：解释选择时安装便利与可靠性应优先于追求极高速度；给安装便利、日常可靠优先的适配器选择方向，不提前保证具体兼容。；解释为何便利和可靠性优先于最高速度，以及怎样按这些条件选择。。

澄清模式：`answer_then_optional_question`；可先回答：True。

- 未知 `usb_interface`：needed_for_specific_item；用于 verify_compatibility。接口影响具体商品连接条件，不阻塞方向性建议
- 未知 `windows_version`：needed_for_specific_item；用于 verify_compatibility。具体版本影响驱动支持；不从历史或目录补成Win11

建议追问：

- 你电脑上可用的USB接口是哪种、Windows是哪个版本？不确定的话，也可以先告诉我电脑型号。（optional；用于后续核对具体适配器，不作为先解释选择方向的门槛）

画像参与：`weak_reference_if_self`。

- 画像不能推断用户电脑接口、系统版本或网络故障原因；历史为正向评价而非购买记录。
- 如果历史倾向高性能，这次明确要求安装便利、可靠性优先，不能奖励迎合历史而违背当次需求。
- 问相关接口问题是合理的；扣分对象应是把可选追问当作拒答门槛，而不是凡提问就扣分。

修订状态：待人审；协议校验通过 ≠ 标准答案批准。完整新结构和审核原输出见同目录 review.json。

## 3. 送朋友通勤耳机：收礼人需求独立于赠送者画像（synth-001-01）

顾客原话：

> 想给朋友挑一副头戴式耳机当礼物，她平时通勤时想少受周围噪声影响，也会用来听音乐和接电话。希望戴久了别太夹耳，预算不用卡得特别死；无线款优先，不过续航和降噪效果我不太会看，有什么合适的选择吗？

### 原始提取与审核

原始包保存已验证提取；不声称恢复完整原响应

原始状态 `quarantined`；失败阶段 `audit`。

```json
{
  "hard_constraints": [
    {
      "field": "product_type",
      "op": "eq",
      "value": "头戴式耳机",
      "quote": "一副头戴式耳机"
    },
    {
      "field": "quantity",
      "op": "eq",
      "value": 1,
      "quote": "一副"
    }
  ],
  "soft_preferences": [
    {
      "need": "通勤时减少受到周围噪声的影响",
      "quote": "她平时通勤时想少受周围噪声影响"
    },
    {
      "need": "适合听音乐和接电话",
      "quote": "也会用来听音乐和接电话"
    },
    {
      "need": "长时间佩戴时不要太夹耳",
      "quote": "希望戴久了别太夹耳"
    },
    {
      "need": "优先考虑无线款",
      "quote": "无线款优先"
    }
  ],
  "unknowns": [
    {
      "slot": "price",
      "reason": "用户表示预算不用卡得特别死，但没有给出具体预算或上限。"
    },
    {
      "slot": "battery_life",
      "reason": "用户表示不太会看续航，没有提出具体续航要求。"
    },
    {
      "slot": "noise_cancellation",
      "reason": "用户表示不太会看降噪效果，没有提出可核验的具体降噪标准。"
    }
  ],
  "purchase_for": "other",
  "purchase_for_quote": "给朋友挑一副头戴式耳机当礼物",
  "needs_clarification": false,
  "clarification_questions": []
}
```

审核来源：previous_supplemental_diagnostic_call；这是已存在的输出，不是本次调用。
模型维度判断：naturalness=pass；extraction_fidelity=pass；fact_boundary=pass；clarification_policy=pass。

- naturalness：顾客表达自然，礼物用途、使用场景、佩戴舒适度和无线偏好衔接合理。
- extraction_fidelity：提取保留了头戴式、单副、通勤降噪、听音乐与接电话、佩戴舒适及无线优先等信息。将预算、续航和降噪的具体标准列为未知，没有把“预算不用卡得特别死”误写成明确价格上限，也没有把送礼对象的偏好归到顾客本人。
- fact_boundary：提取没有用历史评分替朋友推断偏好，也没有把目录标题中的性能宣传当作已验证事实。目录价格所用货币单位未确认，当前提取也未据此作价格结论。
- clarification_policy：顾客是在请求推荐，现有信息足以先按通勤、舒适、无线优先等方向筛选；未追问具体预算、续航或降噪数值并非明显缺漏，因为顾客没有给出这些硬性标准。

当前只读兼容检查：不通过；预审引用不在可见事实中。原文证据未被自动修补。

### 争议与修订建议

- 一副描述购买单位，不限定只展示一个推荐（解释性争议，待人审）。证据：『一副头戴式耳机』。建议：一副可能只是自然单数，暂不设严格购买数量；尤其不能推定只展示一个推荐，待独立人审。
- 预算宽松和不懂续航降噪不能改写成数值门槛（明确的结构或语义问题）。证据：『预算不用卡得特别死；无线款优先，不过续航和降噪效果我不太会看』。建议：无线和舒适保留偏好；不要求先报预算、续航小时数或降噪数值，可以解释选购指标。
- 审核全pass也不代表原输出协议有效（明确的结构或语义问题）。证据：『想给朋友挑一副头戴式耳机当礼物』。建议：保留原模型判断，但分维度reason兼容后仍有不逐字的profile证据；不能自动改写引用或批准样本。

### 修订草案如何使用

请求动作：recommend、explain。

| 强度 | 条件 | 运算和值 | 单位 |
| --- | --- | --- | --- |
| strict | product_type | eq 头戴式耳机 | 未明确 |
| preference | noise_control | prefer 通勤时少受周围噪声影响 | 未明确 |
| preference | wearing_comfort | prefer 长时间佩戴不夹耳 | 未明确 |
| preference | wireless | prefer True | 未明确 |
| preference | music_and_calls | prefer 适合听音乐和接电话 | 未明确 |
| preference | use_case | prefer 通勤 | 未明确 |

明确要回答：给通勤耳机参考并解释续航、降噪的选购指标；解释耳机续航与降噪的选购指标。。

澄清模式：`not_needed`；可先回答：True。

- 未知 `price`：optional_refinement；用于 recommend。没有数值预算，不自行推定赠送者历史价位为朋友预算
- 未知 `battery_hours`：optional_refinement；用于 recommend, explain。未要求明确小时数，不把不会看指标当成必须提问

建议追问：

不设置必须追问；不为了补齐槽位盘问顾客。

画像参与：`do_not_transfer_to_recipient`。

- 不同赠送者画像不应导致朋友的耳机需求凭空改变；若想用历史，必须另有收礼人本人信息与授权。
- 实际舒适和降噪效果需要独立性能或测量证据，不能把营销标题当实测保证。
- 不给具体推荐件数设标准；评分应区分是否满足朋友用途与是否忠实使用画像。

修订状态：待人审；协议校验通过 ≠ 标准答案批准。完整新结构和审核原输出见同目录 review.json。

## 4. 显卡水冷：核对方法不是强制购买安装架（synth-002-00）

顾客原话：

> 我最近想给显卡改用一体式水冷，主要担心显存和供电区域温度太高。看到有显卡水冷安装架，但不确定它能不能配我手头的冷排和显卡；我该先核对哪些型号和尺寸？

### 原始提取与审核

原始包保存已验证提取；不声称恢复完整原响应

原始状态 `quarantined`；失败阶段 `无协议失败；语义审核失败`。

```json
{
  "hard_constraints": [
    {
      "field": "product_type",
      "op": "eq",
      "value": "显卡一体式水冷安装架",
      "quote": "看到有显卡水冷安装架"
    }
  ],
  "soft_preferences": [
    {
      "need": "希望降低显存和供电区域温度",
      "quote": "主要担心显存和供电区域温度太高"
    }
  ],
  "unknowns": [
    {
      "slot": "显卡型号及尺寸",
      "reason": "未提供具体显卡型号或尺寸，无法判断安装架兼容性。"
    },
    {
      "slot": "冷排型号及尺寸",
      "reason": "未提供手头冷排的型号或尺寸，无法核对安装架与冷排的兼容性。"
    },
    {
      "slot": "显存和供电区域的散热覆盖",
      "reason": "未说明安装方案是否能为这些区域提供散热。"
    }
  ],
  "purchase_for": "self",
  "purchase_for_quote": "我手头的冷排和显卡",
  "needs_clarification": true,
  "clarification_questions": [
    {
      "question": "你的显卡具体型号是什么，外形尺寸或PCB信息是否已知？",
      "slot": "显卡型号及尺寸",
      "reason": "需要据此核对安装架是否匹配显卡。"
    },
    {
      "question": "冷排的具体型号和尺寸是什么？",
      "slot": "冷排型号及尺寸",
      "reason": "需要据此核对安装架与冷排的安装兼容性。"
    }
  ]
}
```

审核来源：original_saved_model_audit；这是已存在的输出，不是本次调用。
模型维度判断：naturalness=pass；extraction_fidelity=fail；fact_boundary=pass；clarification_policy=fail。

顾客是在询问应核对哪些兼容信息，并未明确要求购买或限定必须使用“显卡一体式水冷安装架”；把安装架提取为硬性商品类型过度收窄了意图。提取出的显卡、冷排信息缺口及降温诉求基本忠实。澄清问题覆盖了显卡和冷排，但遗漏了水冷本体的具体型号；目录标题显示该安装架针对 Kraken X 系列 AIO，因此仅询问冷排型号不足以判断兼容性。目录标题可作为目录事实引用，但不能据此确认它兼容顾客手头的设备。历史记录是过往好评，不应补充为当前要求；本次提取没有这样做。

当前只读兼容检查：通过；四维理由对象已被旧格式兼容器接受，原状态不翻转。

### 争议与修订建议

- 提到安装架被升格为必须购买安装架（明确的结构或语义问题）。证据：『看到有显卡水冷安装架』。建议：移入背景候选方案；主意图为兼容咨询，动作是guide_verification，不构造必购产品条件。
- 先问显卡和冷排型号不应阻塞核对清单（明确的结构或语义问题）。证据：『我该先核对哪些型号和尺寸？』。建议：先答需要查哪些信息；若后续判断某套组合，才核实显卡/PCB、水冷本体、安装架和空间条件。
- 缺水冷本体型号，不能仅以冷排尺寸判断安装架兼容（明确的结构或语义问题）。证据：『不确定它能不能配我手头的冷排和显卡』。建议：将水冷本体型号列为具体组合核对槽位，目录标题不能直接证明用户组合适配。

### 修订草案如何使用

请求动作：guide_verification。

| 强度 | 条件 | 运算和值 | 单位 |
| --- | --- | --- | --- |
| preference | thermal_coverage | prefer 显存和供电区域降温 | 未明确 |

明确要回答：说明显卡、水冷本体、安装架及安装空间的型号和尺寸核对步骤。

澄清模式：`not_needed`；可先回答：True。

- 未知 `gpu_model_pcb`：needed_for_specific_item；用于 verify_compatibility。只影响后续具体兼容判断，不阻塞介绍核查方法
- 未知 `aio_model`：needed_for_specific_item；用于 verify_compatibility。冷排尺寸不足以代表水冷本体兼容信息
- 未知 `mount_model`：needed_for_specific_item；用于 verify_compatibility。安装架型号尚未提供，不假定就是目录中的型号
- 未知 `case_space`：needed_for_specific_item；用于 verify_compatibility。核查具体组合时需要安装位、冷排尺寸与空间

建议追问：

不设置必须追问；不为了补齐槽位盘问顾客。

画像参与：`not_relevant`。

- 先给核查清单；可说明用户拿到型号后能进一步核对，不要求先填完所有设备信息。
- 通用方法咨询中画像不计必用分；不使用无关历史也是合理行为。
- 后续若用户要求保证某具体组合可装，未知型号才可升级为该新动作的阻塞信息。

修订状态：待人审；协议校验通过 ≠ 标准答案批准。完整新结构和审核原输出见同目录 review.json。

## 5. 显卡散热：比较维度和核查步骤不能漏提（synth-002-01）

顾客原话：

> 我想给显卡改善散热，考虑过换风扇或加装水冷，但不太确定哪种改动更合适。能帮我比较一下不同方案的安装难度、对显卡和供电区域散热的影响吗？如果考虑水冷方案，显卡型号和冷排兼容性要怎么确认？

### 原始提取与审核

原始包保存已验证提取；不声称恢复完整原响应

原始状态 `quarantined`；失败阶段 `无协议失败；语义审核失败`。

```json
{
  "hard_constraints": [],
  "soft_preferences": [],
  "unknowns": [
    {
      "slot": "显卡型号",
      "reason": "用户询问如何确认型号，但没有提供具体型号。"
    },
    {
      "slot": "冷排兼容性",
      "reason": "用户询问如何确认兼容性，但没有提供显卡、水冷组件或机箱信息。"
    }
  ],
  "purchase_for": "unknown",
  "purchase_for_quote": null,
  "needs_clarification": true,
  "clarification_questions": [
    {
      "question": "显卡的具体品牌和型号是什么？",
      "slot": "显卡型号",
      "reason": "确认显卡型号是判断水冷组件兼容性的关键信息。"
    },
    {
      "question": "如果考虑水冷，机箱可安装冷排的位置和尺寸是什么？",
      "slot": "冷排兼容性",
      "reason": "需要机箱冷排空间信息才能判断冷排兼容性。"
    }
  ]
}
```

审核来源：original_saved_model_audit；这是已存在的输出，不是本次调用。
模型维度判断：naturalness=pass；extraction_fidelity=fail；fact_boundary=pass；clarification_policy=fail。

顾客原话自然，明确是在比较显卡散热改动方案，并询问安装难度、显卡及供电区域散热影响，以及确认显卡型号与冷排兼容性的方法。提取结果记录了型号和兼容性未知，但漏掉了这些明确的比较维度及“如何确认”的信息需求。当前信息足以先给出一般性比较和兼容性核查步骤；直接要求提供显卡型号及机箱冷排尺寸，作为回答前的澄清并非必要，可作为后续定制判断的可选追问。提取没有把历史偏好或目录标题当作顾客当前要求，也没有作出超出证据的兼容性断言。

当前只读兼容检查：通过；四维理由对象已被旧格式兼容器接受，原状态不翻转。

### 争议与修订建议

- 仅提未知型号，遗漏明确的方案比较与方法咨询（明确的结构或语义问题）。证据：『能帮我比较一下不同方案的安装难度、对显卡和供电区域散热的影响吗？』。建议：intent记录compare和guide_verification；answer_requirements分别记录安装难度、显卡与供电区域影响和核查步骤。
- 型号未知被视为回答通用比较前必须追问（明确的结构或语义问题）。证据：『显卡型号和冷排兼容性要怎么确认？』。建议：可先给一般性比较与核查方法，不要声称具体温降、风险或兼容性已核实。

### 修订草案如何使用

请求动作：compare、guide_verification。

| 强度 | 条件 | 运算和值 | 单位 |
| --- | --- | --- | --- |
| preference | cooling_goal | prefer 改善显卡散热 | 未明确 |

明确要回答：比较不同散热方案的安装难度；比较对显卡与供电区域散热的影响；说明显卡型号与冷排兼容性的确认方法；给换风扇与加装水冷的条件式取舍建议，不虚构设备事实或唯一方案。。

澄清模式：`not_needed`；可先回答：True。

- 未知 `gpu_model`：needed_for_specific_item；用于 verify_compatibility。用于后续具体组合验证，不阻塞通用比较
- 未知 `cooling_assembly_model`：needed_for_specific_item；用于 verify_compatibility。具体改装组件未知，不能推断具体性能与兼容
- 未知 `case_radiator_space`：needed_for_specific_item；用于 verify_compatibility。机箱安装空间用于进一步判断具体冷排组合

建议追问：

不设置必须追问；不为了补齐槽位盘问顾客。

画像参与：`not_relevant`。

- 当前应按比较和方法覆盖评分，而不是看是否产出推荐商品或强行用历史。
- 提取忠实度包括明确问题是否遗漏，不只是硬条件数量；没有硬条件不等于没有需求。
- 不能用目录中的安装架标题推导用户实际降温效果；未查证的性能判断应明确条件。

修订状态：待人审；协议校验通过 ≠ 标准答案批准。完整新结构和审核原输出见同目录 review.json。

## 6. 网线与接头：原提取缺失，修订只是草案（synth-003-00）

顾客原话：

> 想把路由器挪到另一间屋，得走一段网线，大概50英尺够用。扁平线会不会更好从门边走？另外我有两根短网线想接起来，那个转接头能用吗？

### 原始提取与审核

原提取失败且原响应未保存；缺失不是空需求，新草案不是恢复结果

原始状态 `quarantined`；失败阶段 `extraction`。

没有保存可展示的审核原响应；本次不重新调用审核模型。

### 争议与修订建议

- 提取失败且原响应未保存，不能展示为原模型提取（明确的结构或语义问题）。证据：『大概50英尺够用』。建议：original_validated_extraction=null，明确未恢复原响应；以下结构由Codex拟订，待人审。
- 近似长度与扁平线询问不能改成精确长度及必须扁平（明确的结构或语义问题）。证据：『大概50英尺够用。扁平线会不会更好从门边走？』。建议：长度about/50/ft；扁平与门边走线记录为比较问题，不设扁平线硬过滤。
- 那个转接头指代不明，通用解释不能替代具体兼容结论（解释性争议，待人审）。证据：『另外我有两根短网线想接起来，那个转接头能用吗？』。建议：先解释核查方法，但不肯定该接头能用；当前具体确认动作需要接头标识和两根线端口信息，可与前面的通用回答并行。

### 修订草案如何使用

请求动作：compare、guide_verification、verify_compatibility。

| 强度 | 条件 | 运算和值 | 单位 |
| --- | --- | --- | --- |
| approximate | length | about 15.24 | m |

明确要回答：比较扁平线与其他线形在门边走线的适用条件；说明两根线连接时如何核对接头，并明确当前不能确认该接头兼容；具体转接头能否连接两根现有线暂不能确认，明确待取得接头身份与两端接口后再核查。。

澄清模式：`answer_partially_then_clarify`；可先回答：True。

暂缓给出结论的请求动作：verify_compatibility。

- 未知 `connector_identity`：needed_for_specific_item；用于 verify_compatibility。那个接头没有可识别型号；可先说明方法，但不能确认其能用
- 未知 `existing_cable_ends`：needed_for_specific_item；用于 verify_compatibility。两根线端口与规格未知，用于具体接头核对

建议追问：

- 你说的转接头是什么型号或接口，两根网线的两端是什么插头？发清晰照片也可以。（required_for_action；先回答走线和核查方法；具体接头能否用必须等信息补齐才能确认）

画像参与：`not_relevant`。

- 先回答走线比较与核查方法；verify_compatibility明确暂缓，required_for_action追问是得出具体兼容结论的必要条件，不等于可选。
- 不要推定CAT6、千兆、插头规格或精确米数；两根现有网线不算购买数量或推荐件数。
- 顾客问的是现场走线与接头核查，画像不应替代设备事实；不使用历史不扣分。

修订状态：待人审；协议校验通过 ≠ 标准答案批准。完整新结构和审核原输出见同目录 review.json。

## 7. 网线方案选择：近似长度与先解释后追问（synth-003-01）

顾客原话：

> 我想把路由器接到另一间房的电脑，走线大概需要50英尺，但不太确定要买成品线还是散装线自己处理，也不清楚家里现有的网线能不能用接头延长。能帮我理一下该先确认哪些情况、分别需要什么吗？

### 原始提取与审核

原始包保存已验证提取；不声称恢复完整原响应

原始状态 `quarantined`；失败阶段 `audit`。

```json
{
  "hard_constraints": [
    {
      "field": "product_type",
      "op": "eq",
      "value": "网线",
      "quote": "我想把路由器接到另一间房的电脑"
    },
    {
      "field": "length",
      "op": "eq",
      "value": "大概50英尺",
      "quote": "走线大概需要50英尺"
    }
  ],
  "soft_preferences": [],
  "unknowns": [
    {
      "slot": "线材形式",
      "reason": "顾客不确定应买成品线还是散装线自己处理。"
    },
    {
      "slot": "现有网线与接头的兼容性",
      "reason": "顾客不清楚家里现有的网线能否用接头延长；缺少网线类型、接头规格等信息。"
    }
  ],
  "purchase_for": "self",
  "purchase_for_quote": "我想把路由器接到另一间房的电脑",
  "needs_clarification": true,
  "clarification_questions": [
    {
      "question": "家里现有网线的类型或外皮标识是什么，线头是什么接头？",
      "slot": "现有网线与接头的兼容性",
      "reason": "需要这些信息才能判断能否用接头延长。"
    },
    {
      "question": "这段走线是否需要你自行裁剪、压接或穿过墙体？",
      "slot": "线材形式",
      "reason": "这些条件会影响成品线或散装线哪种更合适。"
    }
  ]
}
```

没有保存可展示的审核原响应；本次不重新调用审核模型。

### 争议与修订建议

- 大概50英尺被写成字符串精确等值条件（明确的结构或语义问题）。证据：『走线大概需要50英尺』。建议：改成数值50、单位ft、approximate/about；不自动规定必须正好50英尺或固定富余比例。
- 要求理清选型和确认步骤，不是已经决定购买某类线（明确的结构或语义问题）。证据：『不太确定要买成品线还是散装线自己处理』。建议：记录compare和guide_verification，成品/散装作为备选方案，不硬筛某个方案。
- 追问有关但不应替代先给方案分支（明确的结构或语义问题）。证据：『能帮我理一下该先确认哪些情况、分别需要什么吗？』。建议：先解释成品、散装、接头延长各要核实什么，再问已有线与走线情况用于具体选择。

### 修订草案如何使用

请求动作：compare、guide_verification。

| 强度 | 条件 | 运算和值 | 单位 |
| --- | --- | --- | --- |
| approximate | length | about 15.24 | m |

明确要回答：解释成品线、散装线和接头延长的选择条件；列出每种方案应确认的现场情况和所需材料；说明成品线、散装线和现有线延长各自适用条件，不强制选唯一商品。。

澄清模式：`answer_then_optional_question`；可先回答：True。

- 未知 `existing_cable_connectors`：needed_for_specific_item；用于 verify_compatibility。实际线与接头信息决定延长方案是否适用
- 未知 `routing_and_termination`：needed_for_specific_item；用于 recommend。是否穿墙和是否需自行端接影响后续具体选择，但不阻塞通用决策解释

建议追问：

- 现有网线和两端插头是什么样的，有外皮标识或照片吗？（optional；用于后续核对延长方案，不阻塞先解释方案分支）
- 这段线要穿墙或小孔吗，你是否打算自己裁线、压接？（optional；据现场条件细化成品线与散装线选择）

画像参与：`not_relevant`。

- 原审核响应未保存，本次不补造模型审核结论；修订必须等待人审。
- 评分方向应是决策解释覆盖和事实边界，不要求给出唯一商品或利用无关历史。
- 长度、路由和端接条件都未定稿，不承诺具体接头兼容或任何真实库存状态。

修订状态：待人审；协议校验通过 ≠ 标准答案批准。完整新结构和审核原输出见同目录 review.json。

## 仍待确认

先确认这些意图、近似条件及追问必要性是否符合购物习惯，再决定是否让模型按新协议重跑。
本次不扩量、不导入正式题集、不改评分权重或校准结论；尚无推荐执行结果，因此也不编造推荐得分。
