# 候选购物请求协议 v2

本协议用于候选生成、盲提取和预审，不修改冻结 v7 题集或正式评分器。它校验结构与逐字证据，不能代替语义审查、推荐质量标注或评分校准。7 条修订只是 Codex 拟订的待人审草案；本次不调用模型，不扩量，不导入正式题集。

## 角色与信息边界

| 角色 | 可以看到 | 不可以补成什么 |
| --- | --- | --- |
| 请求作者 | 匿名目录事实、经授权的过去正向评价、覆盖风格 | 评价不是购买记录；不能证明年龄、职业、现有设备或稳定偏好 |
| 需求提取者 | 仅顾客原话，新的上下文 | 不能读取目录、画像、锚点答案或作者意图来补顾客条件 |
| 样本预审者 | 原话、盲提取、同一冻结目录与匿名历史 | 不能认定为独立金标准，不能根据有限目录断定全站库存 |
| 协议校验器 | 上述结构与可见原文 | 不能判断引用是否充分支持推断，不能认证推荐质量 |

用户已允许当前预览三种模型角色使用同一个 `gpt-6-luna`。分上下文只保证信息隔离，不保证模型误差独立。后续仍须独立人工核对；不把同模型四项通过当作真值。

## 需求结构：rs-shopping-request/2

根对象字段恰为 `schema_version, intent, context_facts, answer_requirements, requirements, unknowns, clarification, recipient`。多余字段、坏类型、非有限数值、非法枚举、虚构引用均拒绝。

| 字段 | 子结构与意义 |
| --- | --- |
| intent | `{primary, actions, evidence}`；primary 区分推荐、比较、兼容咨询、方法咨询、混合、未知；actions 精确保留已请求的动作；evidence 是逐字原话列表 |
| context_facts | `{name, value, quote}` 列表；仅记录顾客自述背景或备选方案，不认证外部事实，不将提及的产品变成必购商品 |
| answer_requirements | `{need, quote}` 列表；明确要回答的比较维度、核查步骤和问题，不等同于商品属性约束 |
| requirements | `{id, kind, field, relation, value, unit, quote}` 列表；id 唯一，field 为英文 snake_case，quote 逐字存在 |
| unknowns | `{slot, reason, needed_for, blocking_level}` 列表；槽位唯一，说明信息对哪个动作才有影响 |
| clarification | `{mode, safe_answer_before_clarification, unresolved_actions, questions}`；区分整体必问、部分可答、可选追问和无需追问 |
| recipient | `{target, quote, profile_policy}`；target=self/other/unknown，unknown 时 quote=null；画像策略单独记录 |

动作是 `recommend, compare, explain, verify_compatibility, guide_verification`。用户问“这个接头能用吗”应保留具体核实动作，不得仅重写成通用方法以绕过信息不足；问“该先核对什么”则不应硬改成选购某件商品。

### 条件强弱、数值与单位

| kind | relation | 例子与边界 |
| --- | --- | --- |
| strict | eq/lte/gte/in/not_in | “不超过30”可以是上限；“Windows 11用”是系统兼容要求，不代表只支持该系统 |
| approximate | about | “三十左右”保留30，单位不明为null；“大概50英尺”保留50和ft；不编造±10%容差 |
| preference | prefer/minimize/maximize | 双频优先、舒适、安装省事、可靠性；不升级为必须，不凭空分配数字权重 |

`purchase_quantity` 与 `recommendation_count` 分开；拒绝模糊字段 `quantity`。数量必须为正整数，但通过此检查不代表原话确实限定数量。“添个”暂不严格化，留给人审；“一副”可拟为购买单位1，不能限制只展示一个推荐。现有两根网线不是买两件。

币种不从目录或历史补出。纯程序事实检查只投影严格条件；近似值和软偏好保留但不产生硬命中。若严格价格条件的单位未知或目录价格单位不同/缺失，保守标为未核实，不算符合预算。事实计数仅针对支持的严格字段，不是综合质量分，也不证明供给中存在完整合格商品。

### 未知信息与多动作澄清

`blocking_level` 是 `required_for_requested_answer`、`needed_for_specific_item`、`optional_refinement`。需要核实具体商品的信息，未必是回答一般方法的前提。

| mode | 先回答 | unresolved_actions | 追问要求 |
| --- | --- | --- | --- |
| required_before_answer | 否；可以说明为何暂不能给请求的结论 | 非空，必须是已请求动作 | blocking 问题覆盖当前阻塞槽位及暂缓动作 |
| answer_partially_then_clarify | 是，先答可答的部分 | 非空，且至少有一个请求动作不暂缓 | required_for_action 问题与暂缓动作关联；不得偷偷确认未知兼容性 |
| answer_then_optional_question | 是 | 空 | 至少一问，全为optional；用于后续细化，不作为拒答门槛 |
| not_needed | 是 | 空 | 零问；不要为补齐槽位盘问顾客 |

questions 每项 `{question, slots, necessity, reason}`，最多两问；slots 必须引用 unknowns。必要追问不得依赖 optional_refinement 槽位，且需关联 unresolved_actions。`safe_answer_before_clarification=true` 表示可安全提供部分或一般性信息，不表示所有子问题都已可给出确定结论。

例如走线建议可以先答，但“那个接头能用吗”暂缓 `verify_compatibility`，需接头标识和现有线端口信息。这与问“该先确认什么”不同：后者可先回答核查步骤，设备追问仅用于下一轮具体判断。

### 画像参与

`profile_policy` 是 `weak_reference_if_self`、`do_not_transfer_to_recipient`、`not_relevant`。当前明确需求优先于历史弱偏好；本人画像仅在授权且对象适用时参与。unknown + weak_reference_if_self 是条件性许可，不是默认把对象判为本人。送礼时不能转移赠送者偏好。通用方法、现场兼容咨询中不用无关历史不扣分，不要求顾客说“照我以前的习惯”。

此标记只是后续评分适用性的输入，尚未形成画像匹配真值或已校准权重；历史不得提供币种、接口、具体型号或性能实测证据。

## 预审结构：rs-shopping-audit/2

```json
{
  "schema_version": "rs-shopping-audit/2",
  "checks": {
    "naturalness": "unknown",
    "extraction_fidelity": "unknown",
    "fact_boundary": "unknown",
    "clarification_policy": "unknown"
  },
  "reasons": {
    "naturalness": "具体理由，非空字符串",
    "extraction_fidelity": "核查意图、遗漏、条件强弱和证据含义",
    "fact_boundary": "核查目录、合成设定和历史是否混用",
    "clarification_policy": "核查问题必要性及暂缓动作"
  },
  "evidence": [{"source": "customer", "quote": "必须替换为输入中的逐字原话"}],
  "issues": []
}
```

以上仅展示类型，不是可直接通过的样本。checks 只能 pass/fail/unknown，reasons 必须完整四维对象，每值非空字符串；evidence 至少一项，source=customer/catalog/profile。目录与画像的引用须逐字出现在对应可见 JSON 文本中；拼接 `history_meaning: ...` 不等于引用实际 JSON。

旧需求格式保留只读验证。旧审核 reason 字符串，或恰有四维且各值非空字符串的对象，可以受控读取；其他形状不盲目转字符串。兼容检查不修补证据、不改写旧响应、不翻转原隔离状态。未来流程若收到旧协议，即使四维通过也保持隔离，标记 legacy_protocol_requires_review。

## 留痕和环境协议

候选包维持 `rs-model-request-candidates/1` 容器，内层需求与审核显式带各自版本。记录原始响应、版本、提示词指纹、模型身份、源题集指纹、用户/家族/统计簇/划分以及冻结环境哈希；失败保留阶段和受控错误，不无界重试、不泄漏凭证。

修订报告另存原始已验证提取、原响应是否实际保存、旧审核原文、只读兼容结果、争议及解释性不确定性、修订作者、待人审状态。不能把未保存的失败提取当作空需求，不能把 Codex 草案冒充新模型输出。原目录、画像授权、用户划分和工具环境引用不改；不据标题修复事实，不重建真实库存。

本次7条的协议校验仅验证可表达性。下一步须先确认争议，再另行决定是否重跑模型及标注推荐质量；正式评分需校准近似预算、用途/画像匹配、回答覆盖和澄清行为。本协议不宣称已有这些得分，更不放开自动进化或上线门禁。

实现入口：`rs_core/offline/evaluation/skill_benchmark/request_contract.py`；候选生成集成：`request_synthesis.py`；离线对照导出：`scripts/evaluation/review_request_candidates.py`。
