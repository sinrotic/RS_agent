# 七条购物请求：v3协议完善及6-luna回归

字段、单位、逐字证据和动作局部澄清已获得明确改善；但真实回归同时暴露了审核误判与用途强度解释分歧。不能把模型全pass当真值或宣布评测已校准。保留首次运行结果，程序的局部作用范围修复只对已有原响应离线回放，不追加调用、不扩量、不入正式集。

只重跑原有7条原话，实际调用gpt-6-luna 14次（每条提取、审核各一次），无生成、无重试、无扩量、无正式导入或上线。
提取只看到原话；审核看到原始新提取及原有商品/画像上下文，不收到旧结果、草案或程序错误。相同模型的新上下文不等于独立模型或人工gold。

## 本轮补齐的规则

- 字段注册和透明别名转换；长度精确统一为米，近似仍是about；币种不明保持null，不推定预算命中。
- 汇总所有逐字引用错误并给程序计算的证据位置；不拼接或修复模型引用。
- 回答目标分类、条件式决策支持；必要信息只暂缓依赖它的当前动作，通用比较和方法先答。
- 画像适用理由独立于self；送礼不迁移赠送者偏好，纯技术咨询不强制用历史。
- 草案补回取舍目标、撤掉耳机严格数量1、修正接口信息的动作绑定。旧草案不覆盖。

## 实测结果与校验修复

逐字引用校验7/7，审核协议校验7/7。
运行时提取结构校验6/7；局部澄清校验修复后，仅对原响应作离线回放，结构校验7/7。没有追加模型调用，也没有改写首次运行状态。
初次程序沿用了v2的全局阻塞假设，误拒了网线接头样本：模型已暂缓兼容判断并设置必要追问，只是把必要等级写成required_for_requested_answer。v3现在按needed_for确定作用范围，必要信息可以只阻塞兼容动作；原输出标签保留，不改成另一等级。
模型审核四维全pass且issues为空为3/7。冻结运行保留2条待人审、5条隔离；离线新校验满足预览门槛的3条也没有自动批准或修改运行状态。
服务返回模型全部为gpt-6-luna，均正常stop；报告token共48228。7条涉及4个画像簇，不是总体语义准确率评测。

| 场景 | 真实回归观察 | 尚余问题 |
| --- | --- | --- |
| synth-000-00 | budget已统一为price；保留about/30和未知币种，Windows 11和双频条件均结构化，引用全部逐字；模型审核却将系统支持要求读成排他条件。 | 审核混淆“必须支持Windows 11”和“只能支持Windows 11” |
| synth-000-01 | Windows进入结构化条件，安装便利、可靠性与相对优先级均保留，也补了decision_support；但审核有可程序证伪的引文误报，并混淆方向性推荐与具体兼容结论。 | 审核声称原话不存在末尾分号，程序证明该引文逐字存在 |
| synth-001-01 | 上一轮两处拼接省略号引用已消失，所有引用逐字；用途进入结构化条件，续航/降噪解释目标保留，送礼do_not_transfer_to_recipient，不造购买或推荐数量。 | 通勤用途与音乐/电话功能应该是门槛还是软偏好仍需独立裁决 |
| synth-002-00 | 本轮只保留guide_verification，不再凭空加入现场verify动作，画像改为not_relevant；但将改装背景记成strict use_case，并没有独立保留显存/供电散热目标和未来组件缺口。 | 改装背景不应自动成为必须购买某类商品的硬过滤 |
| synth-002-01 | 已补decision_support，比较安装难度、显卡/供电散热及型号确认方法均保留；不因缺型号强制拒答，画像not_relevant。模型审核四维全pass且无issues。 | recommend动作含义仍可能混合方案建议与商品推荐 |
| synth-003-00 | 50英尺结构化保留about并规范到15.24m；明确暂缓verify_compatibility，追问接头身份及两根线接口，不把必要追问标optional；纯技术咨询不使用画像。初次被v2全局阻塞假设误拒，修复后离线原响应结构通过。 | 局部必要信息被旧校验误当成整条回答阻塞，已修复但不改旧运行状态 |
| synth-003-01 | 长度不再只藏于背景，50英尺/about规范为15.24m；明确compare、guide和decision_support，先答核查步骤而不盘问，画像not_relevant。模型审核四维全pass且无issues。 | strict用途在方法任务中的含义需统一，unknowns为空不证明现场兼容 |

## 为什么不能把模型审核当标准答案

Windows 11样本的审核把“必须兼容Windows 11”误读成“不能兼容其他系统”。这不是同一个条件：商品支持Windows 10和11并不违反Windows 11需求。操作系统字段的语义仍需明确成兼容支持，而不是产品只能等于一个系统。
第二条的审核称引文末尾分号不存在，但程序定位证明它确实是原话中的连续子串。这是审核误判，不是提取伪引用。该样本的self推断和接口等级仍有独立争议，不能因一个审核理由错误就自动批准整条。
用途强度也存在分歧：咨询背景不应变成硬过滤，但听音乐/接电话可以构成功能需求，不应一律因为没说“必须”就降为可选。当前只有strict/approximate/preference，尚需独立人审确定用途适合做适用性门槛还是偏好；不能以模型全pass替代校准。
以上判断是Codex基于原话和程序证据的分析，不是独立质量标注。首次拒绝结果完整保留，未据分析自动放行。

## 1 无线适配器：近似预算不是硬上限

> 家里台式机的无线网卡不太稳定，想换个USB Wi‑Fi适配器，最好支持双频。主要是Windows 11用，预算三十左右，有合适的吗？

| 版本 | 条件 |
| --- | --- |
| 最初提取 | legacy-hard / product_type / eq / USB Wi‑Fi适配器 ；legacy-hard / operating_system / eq / Windows 11 ；legacy-hard / price / lte / 30  |
| 上一轮6-luna v2 | strict / product_type / eq / USB Wi‑Fi适配器 ；strict / operating_system / eq / Windows 11 ；preference / wireless_band_support / prefer / 双频 ；approximate / budget / about / 30  |
| 修订草案v3 待人审 | strict / product_type / eq / USB Wi-Fi适配器 ；strict / operating_system / eq / Windows 11 ；approximate / price / about / 30 ；preference / dual_band / prefer / True  |
| 本轮6-luna 原始v3 | strict / product_type / eq / USB Wi‑Fi适配器 ；strict / operating_system / eq / Windows 11 ；approximate / price / about / 30 ；preference / dual_band / prefer / True  |
| 程序规范化副本 | strict / product_type / eq / USB Wi‑Fi适配器 ；strict / operating_system / eq / Windows 11 ；approximate / price / about / 30 ；preference / dual_band / prefer / True  |

| 版本 | 动作、澄清与画像 |
| --- | --- |
| 上一轮6-luna | ['recommend']；not_needed；暂缓=[]；画像=weak_reference_if_self |
| 修订草案 | ['recommend']；not_needed；暂缓=[]；画像=weak_reference_if_self |
| 本轮6-luna | ['recommend']；not_needed；暂缓=[]；画像=weak_reference_if_self |

本轮回答目标：

- recommendation：推荐符合所述使用系统、预算和双频偏好的USB Wi‑Fi适配器。；原话：『有合适的吗？』

本轮追问：

没有追问；不要求为了填槽位盘问顾客。

本轮画像适用理由：原话提到家里的台式机，但未明确设备使用者；本轮仅按已提供条件推荐。

原模型审核：

- naturalness=pass：顾客原话是自然、连贯的购物咨询，表达了故障背景、想换的产品、使用系统、预算和双频偏好。
- extraction_fidelity=fail：提取整体忠实，所有 quote 和 intent.evidence 均为顾客原话中的逐字文本；但 r2 将“主要是Windows 11用”提升为严格系统条件，原话说明主要用途，并未明确表示其他系统兼容性不可接受。
- fact_boundary=pass：提取没有把历史好评当作当前偏好或设备事实，也没有从目录推断未证实的价格币种、库存或实际服务状态。目录确有一款标题标明支持 Windows 10/11、双频且标价 26.99 的相关产品。
- clarification_policy=pass：这是推荐请求，现有条件足以先给出候选方向；无需为型号未知而先追问。提取没有把历史画像用于推荐，也没有不必要地阻塞回答。

原模型issues：

- extraction.requirements[r2] 将“主要是Windows 11用”标为 kind="strict"；这比原话所表达的主要使用场景更强，宜表达为 Windows 11 兼容性需求，但不应把它说成明确排斥其他系统的硬条件。

离线回放：结构通过；保留原始运行状态，不自动放行。

Codex对照判断（不是人审）：

- budget已统一为price；保留about/30和未知币种，Windows 11和双频条件均结构化，引用全部逐字；模型审核却将系统支持要求读成排他条件。
- 审核混淆“必须支持Windows 11”和“只能支持Windows 11”。顾客依据：『主要是Windows 11用』。判读：作为兼容条件，商品同时支持其他系统并不违反要求；审核以“没有排斥其他系统”为由否定strict并不成立。需要定义operating_system字段是required_support，不是排他产品属性。现阶段不自动推翻审核或升级样本。
- 画像理由还没有明确授权与相关性边界。顾客依据：『家里台式机』。判读：unknown和条件式weak_reference_if_self可保守保留，但新模型理由只解释未确认使用者。若进入评分，必须由独立画像适用性层检查授权、证据及当前用途相关性，不能仅凭这段理由奖画像分。

## 2 无线适配器：安装便利、可靠性与可选追问

> 家里有台台式机放在路由器旁边不太方便拉网线，最近无线连接也不太稳定，想添个 USB 网络适配器改善一下。比起追求特别高的速度，我更在意安装别太折腾、日常用着可靠；电脑是 Windows，但具体接口和兼容要求我还得确认。能帮我看看哪种更合适吗？

| 版本 | 条件 |
| --- | --- |
| 最初提取 | legacy-hard / product_type / eq / USB 网络适配器 ；legacy-hard / operating_system / eq / Windows ；legacy-hard / quantity / eq / 1  |
| 上一轮6-luna v2 | strict / product_type / eq / USB 网络适配器 ；preference / installation_complexity / minimize / 安装别太折腾 ；preference / reliability / maximize / 日常用着可靠  |
| 修订草案v3 待人审 | strict / product_type / eq / USB网络适配器 ；strict / operating_system / eq / Windows ；preference / installation_difficulty / minimize / 安装便利 ；preference / reliability / prefer / 日常可靠性优先于极高速度  |
| 本轮6-luna 原始v3 | strict / product_type / eq / USB网络适配器 ；strict / operating_system / eq / Windows ；strict / use_case / eq / 改善台式机无线连接 ；preference / installation_difficulty / minimize / 安装别太折腾 ；preference / reliability / maximize / 日常用着可靠 ；preference / priority / prefer / 安装便利和日常可靠性优先于特别高的速度  |
| 程序规范化副本 | strict / product_type / eq / USB网络适配器 ；strict / operating_system / eq / Windows ；strict / use_case / eq / 改善台式机无线连接 ；preference / installation_difficulty / minimize / 安装别太折腾 ；preference / reliability / maximize / 日常用着可靠 ；preference / priority / prefer / 安装便利和日常可靠性优先于特别高的速度  |

| 版本 | 动作、澄清与画像 |
| --- | --- |
| 上一轮6-luna | ['recommend']；answer_then_optional_question；暂缓=[]；画像=weak_reference_if_self |
| 修订草案 | ['recommend']；answer_then_optional_question；暂缓=[]；画像=weak_reference_if_self |
| 本轮6-luna | ['recommend']；not_needed；暂缓=[]；画像=weak_reference_if_self |

本轮回答目标：

- recommendation：建议适合改善台式机无线连接的USB网络适配器类型或选购方向。；原话：『想添个 USB 网络适配器改善一下』
- decision_support：说明安装便利性、日常可靠性与速度之间的取舍及选择条件，不强行给出唯一结论。；原话：『比起追求特别高的速度，我更在意安装别太折腾、日常用着可靠；』
- explanation：解释选购方向如何对应用户在意的安装便利和日常可靠。；原话：『我更在意安装别太折腾、日常用着可靠』

本轮追问：

没有追问；不要求为了填槽位盘问顾客。

本轮画像适用理由：用户描述家中自己的台式机并请求选购建议；如有相关的本人历史信息，可弱参考，但不假定其相关性。

原模型审核：

- naturalness=pass：顾客以自然口语说明台式机、无线连接问题、偏好和信息尚未确认之处，并提出选购建议请求；这是合理的购物咨询场景。
- extraction_fidelity=fail：提取大体抓住推荐目标及安装、可靠性、速度取舍，但 answer_requirements[1].quote 在原文末尾多了一个分号，属于非逐字引文。此外，“推荐台式机无线连接适配器”的意图基本忠实，但把“电脑是 Windows”提升为严格操作系统条件，与顾客明确说兼容要求尚待确认不符。
- fact_boundary=fail：requirements.r2 将 Windows 记为严格筛选条件，但顾客只陈述电脑是 Windows，并说明具体接口和兼容要求还要确认；应将其作为已知背景，而非已确认的兼容硬条件。recipient 的 self 及画像弱参考推断缺少足够证据：顾客说“家里有台台式机”，没有明确说设备属于本人。目录价格单位未确认，也不能据此补出币种；目录只有有限样本，不代表全站库存或服务状态。
- clarification_policy=fail：可以先给出选购方法，不必因接口和兼容未知而阻止推荐方向；但当前推荐依赖进一步确认时，应将相关动作列入 unresolved_actions，并把接口、具体兼容要求作为 required_for_action 的局部追问，而非仅 optional_refinement。现有 clarification 标为 not_needed 且没有未解决动作，不符合条件。

原模型issues：

- 提取结果 answer_requirements[1].quote 为“比起追求特别高的速度，我更在意安装别太折腾、日常用着可靠；”，末尾分号不在顾客原话中，属于非逐字引用。
- requirements.r2 将“电脑是 Windows”设为 strict operating_system 条件；原话仅确认系统背景，并明确表示兼容要求仍需确认。
- recipient.target=self 及 profile_policy=weak_reference_if_self 缺少明确的本人归属证据；家庭有台式机不等于确认由本人使用或购买。
- 接口和兼容信息应可通过先行给出选购方向、再对具体型号作局部确认来处理；clarification.unresolved_actions 为空，且 unknowns 的 blocking_level 仅为 optional_refinement。
- 不要根据目录价格填写货币单位；price_unit 明示 currency_unconfirmed。

离线回放：结构通过；保留原始运行状态，不自动放行。

Codex对照判断（不是人审）：

- Windows进入结构化条件，安装便利、可靠性与相对优先级均保留，也补了decision_support；但审核有可程序证伪的引文误报，并混淆方向性推荐与具体兼容结论。
- 审核声称原话不存在末尾分号，程序证明该引文逐字存在。顾客依据：『比起追求特别高的速度，我更在意安装别太折腾、日常用着可靠；』。判读：evidence_validation中该quote有效且有准确位置。它不是拼接或伪引用；审核的这条fail依据错误。其他问题需各自判断，不能因此自动批准整条。
- 接口未知的适用动作仍有歧义。顾客依据：『具体接口和兼容要求我还得确认』。判读：本轮只要求选择方向，缺接口不应阻塞一般解释；但具体适配判断的接口信息也不应永远标为optional_refinement。修订草案将它绑定未来verify_compatibility/needed_for_specific_item；审核直接要求把recommend暂缓，同样可能扩大了当前要求。
- 家庭设备不直接证明本人使用，背景转成“不追求高速”也可能强于相对偏好。顾客依据：『家里有台台式机』。判读：self有解释空间，草案保留unknown；当前可靠和便利优先不表示拒绝高速。新模型requirements.priority更忠实，context中的“不追求”不应参与排他筛选。

## 3 送朋友通勤耳机：收礼人需求独立于赠送者画像

> 想给朋友挑一副头戴式耳机当礼物，她平时通勤时想少受周围噪声影响，也会用来听音乐和接电话。希望戴久了别太夹耳，预算不用卡得特别死；无线款优先，不过续航和降噪效果我不太会看，有什么合适的选择吗？

| 版本 | 条件 |
| --- | --- |
| 最初提取 | legacy-hard / product_type / eq / 头戴式耳机 ；legacy-hard / quantity / eq / 1  |
| 上一轮6-luna v2 | strict / product_type / eq / 头戴式耳机 ；preference / wearing_pressure / minimize / 夹耳感 ；preference / wireless / prefer / True ；preference / noise_cancellation / maximize / 减少周围噪声影响  |
| 修订草案v3 待人审 | strict / product_type / eq / 头戴式耳机 ；preference / noise_control / prefer / 通勤时少受周围噪声影响 ；preference / wearing_comfort / prefer / 长时间佩戴不夹耳 ；preference / wireless / prefer / True ；preference / music_and_calls / prefer / 适合听音乐和接电话 ；preference / use_case / prefer / 通勤  |
| 本轮6-luna 原始v3 | strict / product_type / eq / 头戴式耳机 ；strict / use_case / eq / 通勤 ；strict / music_and_calls / eq / 听音乐和接电话 ；preference / wearing_comfort / minimize / 夹耳 ；preference / wireless / prefer / 无线 ；preference / noise_control / maximize / 减少通勤时受周围噪声影响  |
| 程序规范化副本 | strict / product_type / eq / 头戴式耳机 ；strict / use_case / eq / 通勤 ；strict / music_and_calls / eq / 听音乐和接电话 ；preference / wearing_comfort / minimize / 夹耳 ；preference / wireless / prefer / 无线 ；preference / noise_control / maximize / 减少通勤时受周围噪声影响  |

| 版本 | 动作、澄清与画像 |
| --- | --- |
| 上一轮6-luna | ['recommend', 'explain']；not_needed；暂缓=[]；画像=do_not_transfer_to_recipient |
| 修订草案 | ['recommend', 'explain']；not_needed；暂缓=[]；画像=do_not_transfer_to_recipient |
| 本轮6-luna | ['recommend', 'explain']；not_needed；暂缓=[]；画像=do_not_transfer_to_recipient |

本轮回答目标：

- recommendation：推荐适合通勤、听音乐和接电话，并兼顾佩戴舒适度的头戴式耳机选择方向。；原话：『有什么合适的选择吗？』
- explanation：说明如何判断耳机续航和降噪效果。；原话：『续航和降噪效果我不太会看』
- decision_support：解释续航、降噪、佩戴舒适度和无线需求之间的权衡，并按使用偏好提供选择条件，而非强行给出唯一结论。；原话：『续航和降噪效果我不太会看』

本轮追问：

没有追问；不要求为了填槽位盘问顾客。

本轮画像适用理由：这是为朋友挑选礼物，不应将赠送者的个人偏好或历史迁移给收礼者。

原模型审核：

- naturalness=pass：顾客原话自然、连贯，包含送礼对象、通勤用途、主要使用场景、佩戴舒适偏好、无线优先和对续航与降噪判断的求助。
- extraction_fidelity=fail：所有列出的 quote 和 intent.evidence 都是顾客原话中的逐字片段，没有发现拼接或伪引用；但 r2、r3 将使用场景标成 strict，强于原话表达。通勤、听音乐和接电话是预期用途，并未明确说成不可妥协的硬条件。其余主要需求和回答目标提取基本忠实。
- fact_boundary=pass：提取没有把目录标题中的宣传语当成已验证的续航、降噪或舒适度事实，也没有把赠送者的历史偏好转移给朋友。目录中的商品信息不足以证实具体产品表现，但本提取没有据此作出产品事实断言。
- clarification_policy=pass：顾客在询问选择建议，并明确表示不熟悉续航和降噪的判断方法；可以先解释判断方法并给出选择方向，不必先追问型号或补充偏好。没有当前动作必须依赖但被遗漏的必要信息。

原模型issues：

- requirements.r2 将“平时通勤时”标为 strict；这表达使用场景，不足以证明它是不可妥协的严格条件。
- requirements.r3 将“听音乐和接电话”标为 strict；原话说明预期用途，并未明确设为硬性门槛。

离线回放：结构通过；保留原始运行状态，不自动放行。

Codex对照判断（不是人审）：

- 上一轮两处拼接省略号引用已消失，所有引用逐字；用途进入结构化条件，续航/降噪解释目标保留，送礼do_not_transfer_to_recipient，不造购买或推荐数量。
- 通勤用途与音乐/电话功能应该是门槛还是软偏好仍需独立裁决。顾客依据：『也会用来听音乐和接电话』。判读：审核把r2/r3 strict全部判强，但顾客预期用途也可以隐含必要功能；不能机械要求每条都说“必须”。不支持通话的设备未必是合格推荐。需要定义用途适用性、功能能力与程度偏好，再做标注校准。
- “不夹耳”和减少噪声的评价证据仍未构建。顾客依据：『希望戴久了别太夹耳』。判读：新提取保持偏好是合理的，但真正给推荐打分还需产品性能/舒适证据或独立质量标注，标题不能证明戴久不夹耳。这轮没有执行推荐，不能计算用途匹配满分。

## 4 显卡水冷：核对方法不是强制购买安装架

> 我最近想给显卡改用一体式水冷，主要担心显存和供电区域温度太高。看到有显卡水冷安装架，但不确定它能不能配我手头的冷排和显卡；我该先核对哪些型号和尺寸？

| 版本 | 条件 |
| --- | --- |
| 最初提取 | legacy-hard / product_type / eq / 显卡一体式水冷安装架  |
| 上一轮6-luna v2 | 没有结构化商品条件（回答目标另列） |
| 修订草案v3 待人审 | preference / thermal_coverage / prefer / 显存和供电区域降温  |
| 本轮6-luna 原始v3 | strict / use_case / eq / 给显卡改用一体式水冷  |
| 程序规范化副本 | strict / use_case / eq / 给显卡改用一体式水冷  |

| 版本 | 动作、澄清与画像 |
| --- | --- |
| 上一轮6-luna | ['verify_compatibility', 'guide_verification']；answer_then_optional_question；暂缓=[]；画像=weak_reference_if_self |
| 修订草案 | ['guide_verification']；not_needed；暂缓=[]；画像=not_relevant |
| 本轮6-luna | ['guide_verification']；not_needed；暂缓=[]；画像=not_relevant |

本轮回答目标：

- verification_steps：说明安装前应核对哪些型号和尺寸，以及如何逐项核验显卡水冷安装架与冷排、显卡的适配情况。；原话：『我该先核对哪些型号和尺寸？』

本轮追问：

没有追问；不要求为了填槽位盘问顾客。

本轮画像适用理由：这是纯技术核查方法咨询，没有商品推荐，不需要使用画像。

原模型审核：

- naturalness=pass：顾客的问题自然且明确，是询问安装前如何核对型号和尺寸的技术咨询。
- extraction_fidelity=fail：主要意图、回答目标和背景顾虑提取基本忠实；但把改装用途记为 strict 商品要求，容易将咨询背景误作可评分的硬条件。所列引用均为原文连续逐字片段。
- fact_boundary=pass：提取结果没有把目录商品或历史记录冒充为顾客当前设备，也没有据历史推断其设备型号或偏好。将其标为 self 有顾客关于自己手头设备及改装计划的文本依据；画像不相关的处理恰当。
- clarification_policy=pass：顾客询问核对方法，可以先说明检查项目，不必先索取显卡和冷排型号；未知型号只会限制对具体兼容性的判断，并不妨碍回答方法。

原模型issues：

- extraction.requirements[0] 将“给显卡改用一体式水冷”标为 strict 的 use_case；它表达的是改装背景或用途，不宜据此当作商品筛选硬条件。
- extraction.unknowns 为空，但具体显卡、冷排及安装架型号在当前请求中未知。由于顾客问的是核对方法而非要求立即验证具体组合，这些未知不构成必须先追问的门槛。

离线回放：结构通过；保留原始运行状态，不自动放行。

Codex对照判断（不是人审）：

- 本轮只保留guide_verification，不再凭空加入现场verify动作，画像改为not_relevant；但将改装背景记成strict use_case，并没有独立保留显存/供电散热目标和未来组件缺口。
- 改装背景不应自动成为必须购买某类商品的硬过滤。顾客依据：『我最近想给显卡改用一体式水冷』。判读：当前问题是核查步骤；strict use_case容易被下游错误用于筛商品。审核对此拒绝有依据，应保留背景/回答目标而非必购条件。草案未设置必购类型。
- 显存/供电区域需求与未来具体兼容缺口未充分结构化。顾客依据：『主要担心显存和供电区域温度太高』。判读：新结果只在背景记录顾虑、unknowns为空。不能阻塞当前方法，但未来要验证显卡/PCB、水冷本体、安装架与空间时必须核对信息，且核查清单应覆盖这部分散热而非只看冷排尺寸。草案已显式保留。

## 5 显卡散热：比较维度和核查步骤不能漏提

> 我想给显卡改善散热，考虑过换风扇或加装水冷，但不太确定哪种改动更合适。能帮我比较一下不同方案的安装难度、对显卡和供电区域散热的影响吗？如果考虑水冷方案，显卡型号和冷排兼容性要怎么确认？

| 版本 | 条件 |
| --- | --- |
| 最初提取 | 没有结构化商品条件（回答目标另列） |
| 上一轮6-luna v2 | 没有结构化商品条件（回答目标另列） |
| 修订草案v3 待人审 | preference / cooling_goal / prefer / 改善显卡散热  |
| 本轮6-luna 原始v3 | preference / use_case / prefer / 改善显卡散热  |
| 程序规范化副本 | preference / use_case / prefer / 改善显卡散热  |

| 版本 | 动作、澄清与画像 |
| --- | --- |
| 上一轮6-luna | ['compare', 'explain', 'guide_verification']；not_needed；暂缓=[]；画像=weak_reference_if_self |
| 修订草案 | ['compare', 'guide_verification']；not_needed；暂缓=[]；画像=not_relevant |
| 本轮6-luna | ['recommend', 'compare', 'guide_verification']；not_needed；暂缓=[]；画像=not_relevant |

本轮回答目标：

- recommendation：针对改善显卡散热的目标，给出改动方案建议。；原话：『我想给显卡改善散热』
- comparison：比较不同改动方案的安装难度，以及对显卡和供电区域散热的影响。；原话：『比较一下不同方案的安装难度、对显卡和供电区域散热的影响』
- decision_support：说明方案选择的权衡和适用条件，帮助判断换风扇或加装水冷哪种更合适，不强行给出不依赖条件的唯一结论。；原话：『不太确定哪种改动更合适』
- verification_steps：说明如何确认显卡型号与冷排兼容性。；原话：『显卡型号和冷排兼容性要怎么确认』

本轮追问：

没有追问；不要求为了填槽位盘问顾客。

本轮画像适用理由：这是关于散热改动方案比较和兼容性核查方法的技术咨询，不涉及商品推荐画像。

原模型审核：

- naturalness=pass：顾客的散热目标、方案比较需求及兼容性核查问题连贯自然；有限目录中没有显卡型号专用水冷产品，不会使咨询本身变得不自然。
- extraction_fidelity=pass：提取保留了改善显卡散热的目标、换风扇与水冷的候选方案、安装难度和显卡及供电区域散热的比较维度，以及兼容性核查方法。所列 quote 和 intent.evidence 均为顾客原话中的连续逐字文本，没有发现拼接、改写或省略号伪引用。将选择需求提取为 decision_support 也符合“哪种改动更合适”的询问。
- fact_boundary=pass：提取未把目录中的单个水冷安装套件或匿名历史好评补成当前型号、兼容性、设备条件或本人偏好。目录与历史不能证明当前显卡和冷排兼容，也不能据此断言哪种方案对顾客设备最合适。
- clarification_policy=pass：顾客问的是如何确认型号与兼容性，可先提供核查方法；没有给出型号并不妨碍比较一般方案或说明验证步骤。因此无需把具体型号设为回答门槛，not_needed 与空 unresolved_actions 合理。

原模型issues：

空。

离线回放：结构通过；保留原始运行状态，不自动放行。

Codex对照判断（不是人审）：

- 已补decision_support，比较安装难度、显卡/供电散热及型号确认方法均保留；不因缺型号强制拒答，画像not_relevant。模型审核四维全pass且无issues。
- recommend动作含义仍可能混合方案建议与商品推荐。顾客依据：『不太确定哪种改动更合适』。判读：新模型加入recommend但理由又说不涉及商品推荐画像；作为条件式改装方案建议可以合理，但不能用这个动作迫使Agent报商品或使用购物历史。当前允许recommend配not_relevant，后续应区分方案建议和商品推荐动作。
- 通用比较过关不代表具体改装效果或兼容已核实。顾客依据：『对显卡和供电区域散热的影响』。判读：仍不能凭目录安装架标题或历史评价承诺温降、风险或兼容性；待人审时要检查比较覆盖和证据边界。本轮仅提取/预审，不计算推荐质量。

## 6 网线与接头：原提取缺失，修订只是草案

> 想把路由器挪到另一间屋，得走一段网线，大概50英尺够用。扁平线会不会更好从门边走？另外我有两根短网线想接起来，那个转接头能用吗？

| 版本 | 条件 |
| --- | --- |
| 最初提取 | 原提取失败且响应未保存，不按空需求处理 |
| 上一轮6-luna v2 | approximate / cable_length / about / 50 英尺 |
| 修订草案v3 待人审 | approximate / length / about / 15.24 m |
| 本轮6-luna 原始v3 | strict / product_type / eq / 网线 ；approximate / length / about / 50 英尺；strict / use_case / eq / 将路由器挪到另一间屋并走一段网线  |
| 程序规范化副本 | strict / product_type / eq / 网线 ；approximate / length / about / 15.24 m；strict / use_case / eq / 将路由器挪到另一间屋并走一段网线  |

| 版本 | 动作、澄清与画像 |
| --- | --- |
| 上一轮6-luna | ['compare', 'explain', 'verify_compatibility']；answer_then_optional_question；暂缓=[]；画像=weak_reference_if_self |
| 修订草案 | ['compare', 'guide_verification', 'verify_compatibility']；answer_partially_then_clarify；暂缓=['verify_compatibility']；画像=not_relevant |
| 本轮6-luna | ['compare', 'verify_compatibility']；answer_partially_then_clarify；暂缓=['verify_compatibility']；画像=not_relevant |

本轮回答目标：

- comparison：比较扁平网线与其他网线在沿门边走线方面的适用性。；原话：『扁平线会不会更好从门边走？』
- decision_support：说明选择时的权衡与条件分支，帮助判断扁平线是否适合门边走线，不强行给唯一结论。；原话：『扁平线会不会更好从门边走？』
- compatibility_verdict：判断所指转接头能否连接这两根短网线。；原话：『那个转接头能用吗？』

本轮追问：

- 请说明转接头的具体类型或接口，以及两根短网线两端的接口类型（如都是RJ45吗？）。（required_for_action；槽位['adapter_identity', 'short_cable_interfaces']）

本轮画像适用理由：这是关于走线比较和接口兼容核查的技术咨询，不涉及商品推荐或画像使用。

原模型审核：

- naturalness=pass：顾客原话自然地结合了搬动路由器、约50英尺走线、门边布线比较和连接两根短网线的兼容性问题；这些需求可以先部分回答，再对接头问题追问。
- extraction_fidelity=pass：提取准确涵盖了走线用途、约50英尺长度、扁平线与门边走线的比较目标，以及转接头兼容性核查。所列quote及intent.evidence均为顾客原话中的逐字连续文本，没有发现拼接、改写或省略号伪引用；约50英尺保留为近似长度。
- fact_boundary=pass：提取结果没有把目录中的RJ45耦合器擅自认定为顾客所说的转接头，也没有用历史评分推断顾客设备或偏好。画像标记为not_relevant，符合这是纯技术咨询且没有推荐动作的情形。
- clarification_policy=pass：对走线比较可以先提供一般方法与条件分支，不必因具体型号未知而阻塞回答；判断特定转接头能否连接两根线则需要知道转接头身份和线缆接口。提取结果将该动作列为未解决，并设置required_for_action局部追问，处理恰当。

原模型issues：

空。

冻结运行校验错误：部分回答必须保留可答动作，并为暂缓结论提供必要追问

离线回放：结构通过；保留原始运行状态，不自动放行。

Codex对照判断（不是人审）：

- 50英尺结构化保留about并规范到15.24m；明确暂缓verify_compatibility，追问接头身份及两根线接口，不把必要追问标optional；纯技术咨询不使用画像。初次被v2全局阻塞假设误拒，修复后离线原响应结构通过。
- 局部必要信息被旧校验误当成整条回答阻塞，已修复但不改旧运行状态。顾客依据：『那个转接头能用吗？』。判读：模型已设answer_partially_then_clarify、unresolved verify和required_for_action，局部行为正确。required_for_requested_answer作用域由needed_for绑定，兼容结论必需不等于比较前必需。程序仅适配校验副本，原标签及首次隔离状态保持。
- 已有线与走线背景的strict use_case仍有下游误用风险。顾客依据：『想把路由器挪到另一间屋，得走一段网线』。判读：与第4条一样，方法/现场背景转为strict用途的解释尚未统一。新审核此处全pass不证明语义没有分歧；维持原始隔离状态，由独立人审决定用途的评分参与方式。

透明规范化：

- /requirements/1：{'field': 'length', 'value': 50, 'unit': '英尺'} → {'field': 'length', 'value': 15.24, 'unit': 'm'}。

## 7 网线方案选择：近似长度与先解释后追问

> 我想把路由器接到另一间房的电脑，走线大概需要50英尺，但不太确定要买成品线还是散装线自己处理，也不清楚家里现有的网线能不能用接头延长。能帮我理一下该先确认哪些情况、分别需要什么吗？

| 版本 | 条件 |
| --- | --- |
| 最初提取 | legacy-hard / product_type / eq / 网线 ；legacy-hard / length / eq / 大概50英尺  |
| 上一轮6-luna v2 | 没有结构化商品条件（回答目标另列） |
| 修订草案v3 待人审 | approximate / length / about / 15.24 m |
| 本轮6-luna 原始v3 | strict / product_type / eq / 网线 ；strict / use_case / eq / 连接路由器与另一间房的电脑 ；approximate / length / about / 50 英尺 |
| 程序规范化副本 | strict / product_type / eq / 网线 ；strict / use_case / eq / 连接路由器与另一间房的电脑 ；approximate / length / about / 15.24 m |

| 版本 | 动作、澄清与画像 |
| --- | --- |
| 上一轮6-luna | ['explain', 'guide_verification']；answer_then_optional_question；暂缓=[]；画像=not_relevant |
| 修订草案 | ['compare', 'guide_verification']；answer_then_optional_question；暂缓=[]；画像=not_relevant |
| 本轮6-luna | ['compare', 'guide_verification']；not_needed；暂缓=[]；画像=not_relevant |

本轮回答目标：

- comparison：比较成品线与散装线自行处理所需的准备、操作和适用情形；原话：『不太确定要买成品线还是散装线自己处理』
- decision_support：说明选择成品线或散装线的权衡与条件分支，不预设唯一选择；原话：『不太确定要买成品线还是散装线自己处理』
- verification_steps：列出购买或延长前应先确认的情况，以及各自需要准备或核对的内容；原话：『能帮我理一下该先确认哪些情况、分别需要什么吗？』

本轮追问：

没有追问；不要求为了填槽位盘问顾客。

本轮画像适用理由：请求聚焦于布线选项的比较和核查方法，不涉及商品推荐或个人画像。

原模型审核：

- naturalness=pass：顾客自然地询问约50英尺的路由器到异房电脑布线方案，以及成品线、散装线和接头延长的取舍与核查步骤。
- extraction_fidelity=pass：提取覆盖了比较、决策支持、购买或延长前的核查步骤，以及用途和约略长度。所列 quote 与 intent.evidence 均为顾客原文中的逐字片段；约50英尺被正确记录为近似长度。
- fact_boundary=pass：提取没有把目录商品信息或历史记录当作顾客当前要求，也没有凭历史补出设备兼容性或个人偏好；目录不足以证明实际库存、价格币种或顾客现有线材的兼容情况。
- clarification_policy=pass：这是询问先确认什么、分别需要什么的流程咨询，并非要求判定某个已知接头能否连接某两根已知线材。可先说明通用核查方法，并把线材类型、端头和接头规格列作后续核实项，无需先追问才能回答。

原模型issues：

空。

离线回放：结构通过；保留原始运行状态，不自动放行。

Codex对照判断（不是人审）：

- 长度不再只藏于背景，50英尺/about规范为15.24m；明确compare、guide和decision_support，先答核查步骤而不盘问，画像not_relevant。模型审核四维全pass且无issues。
- strict用途在方法任务中的含义需统一，unknowns为空不证明现场兼容。顾客依据：『能帮我理一下该先确认哪些情况、分别需要什么吗？』。判读：顾客要核查分支而非现在判断某接头，not_needed合理，也不必把未来每个槽位都当必问。但下游不能据unknowns空认为现场条件已齐全；用途不能误作强制买成品线或散装线。草案保留未来信息缺口作为安全提示。
- 已有线延长分支是否充分覆盖仍需看真实Agent回答。顾客依据：『家里现有的网线能不能用接头延长』。判读：新回答目标的比较与决策文字主要指成品/散装，核查目标较泛。独立人审和后续执行评分要确认延长分支也被覆盖，不把模型allpass当覆盖证明。

透明规范化：

- /requirements/2：{'field': 'length', 'value': 50, 'unit': '英尺'} → {'field': 'length', 'value': 15.24, 'unit': 'm'}。

## 边界与下一步

正式评测集仍为2899条，未改旧包状态、旧草案、旧审核和模型响应。协议与校验修复不代表推荐评分已校准：本轮没有执行Qwen推荐、没有满意度标签，也没有人工质量批准。
下一步应先人工裁决用途/兼容强度、购买对象和审核误报，再补语义审核校准；不要扩量或把这七条自动升级gold。完整原提取、v2重跑、v3草案、真实响应、规范化与回放在regression.json中保留。
