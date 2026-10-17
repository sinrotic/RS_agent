# Agent Conversation Context

本上下文描述 Agent 会话从接收用户消息到完成回答期间形成的事实、运行状态和管理视图，并明确它与用户长期记忆的区别。

## Language

**Session（会话）**：
由 `session_id` 标识的一段连续对话；连续 24 小时无活动后结束，之后的消息属于新会话。
_Avoid_: Conversation、Thread

**Instance-independent Session（实例无关会话）**：
不绑定某个 Agent 服务实例、可由任意实例继续处理的 Session；实例亲和仅用于性能优化，不构成正确性前提。
_Avoid_: Sticky Session、Instance-bound Session

**Turn（轮次）**：
由 Session 内唯一的 `turn_id` 标识，从一条用户消息开始，到该消息对应的最终回答或失败结果成为持久事实为止的一次交互；同一次发送的重试沿用原 `turn_id`，客户端送达确认不属于完成条件。
_Avoid_: Request、Round

**Session Execution Lane（会话执行通道）**：
同一 Session 内按接收顺序串行执行 Turn、分配事件顺序并更新 Effective Context 的唯一逻辑通道。
_Avoid_: Concurrent Turn、Global Queue

**Session Event（会话事件）**：
会话中已经发生、足以影响回放、恢复或审计的完整语义事实。
_Avoid_: Token Event、Stream Delta

**Durable Session History（持久会话历史）**：
按会话确定顺序保存的 Session Event 集合，是恢复会话实际过程的权威记录。
_Avoid_: Chat Cache、Transcript Cache

**Hot Session State（热会话状态）**：
活跃会话当前运行所需、可由 Durable Session History 重建的临时视图，不具有事实权威性。
_Avoid_: Session Source、Persistent Session

**Effective Context（有效上下文）**：
为继续当前 Session 而保留的模型相关会话内容，由压缩摘要、原样保留的近期事件和压缩后事件组成。
_Avoid_: Recoverable Session、完整会话

**Context Checkpoint（上下文检查点）**：
记录 Effective Context 压缩范围和原样事件起点的权威恢复标记。
_Avoid_: Session Summary、Cache Snapshot

**Safe Compaction Boundary（安全压缩边界）**：
所有既有 Session Event 已持久化、没有未完成工具调用且即将发起下一次模型调用的状态点。
_Avoid_: Token Threshold、Stream Pause

**Emergency Context Truncation（紧急上下文裁剪）**：
常规压缩无法解除上下文超限时，对 Effective Context 中最旧的完整语义组执行的可审计有损裁剪，不影响 Durable Session History。
_Avoid_: History Deletion、Silent Truncation

**Replay-safe Tool（可重放工具）**：
重复执行只会重复读取或计算、不会造成不可逆外部副作用的 Agent 工具。
_Avoid_: Idempotent Tool、User Action

**Session Projection（会话投影）**：
面向会话管理和查询，从会话事实派生出的标题、摘要、状态和活动时间等视图。
_Avoid_: Session History、Event Store

**Long-term Memory（长期记忆）**：
以 `user_id` 为范围、可跨多个 Session 使用的用户相关知识，不属于会话历史。
_Avoid_: Session Memory、Conversation Cache

## Identity and Catalog Language

**Account（账号）**：
能够完成认证并访问应用能力的产品身份；它可以绑定一个用于个性化推荐的 Profile User，但两者不是同一概念。
_Avoid_: Profile User、Dataset User

**Profile User（画像用户）**：
由推荐行为、偏好和历史记录标识的个性化主体；它可以来自数据集，并通过绑定关系服务于一个 Account。
_Avoid_: Account、Login User

**Catalog Item（目录商品）**：
由稳定 `item_id` 标识、承载标题、类目、品牌、价格、图片等商品事实的标准商品记录。
_Avoid_: Candidate Item、Recommendation Result

**Display Product（展示商品）**：
面向界面的商品视图，由 Catalog Item 的商品事实与本次推荐的排序、理由等展示信息组合而成。
_Avoid_: Catalog Source、Candidate Record

## Recommendation Language

**Candidate Item（候选商品）**：
进入某次推荐处理、尚未形成最终展示结果的商品标识及其召回或排序证据。
_Avoid_: Catalog Item、Display Product

**Recall Source（召回源）**：
按一种确定策略为目标用户或查询提供 Candidate Item 的候选来源。
_Avoid_: Ranking Model、RAG Evidence

**Ranking Route（排序路由）**：
受治理登记约束、对候选集合执行打分、排序和降级选择的当前处理路径。
_Avoid_: Recall Source、Experiment Script

**Route Gate（路由门禁）**：
依据数据范围、质量、可复现性和资源证据，决定实验产物是否允许进入更高使用级别的治理判断。
_Avoid_: Test Pass、Artifact Exists

**Read-only Shadow Evidence（只读影子证据）**：
只用于诊断和观察、不得生成候选、替换排序输入或授权主路晋级的旁路证据。
_Avoid_: Candidate Source、Production Route

**Recommendation Artifact（推荐产物）**：
由数据加工、训练、索引构建或评估产生，带有范围、版本和可复现元数据的推荐系统资产。
_Avoid_: Source Code、Untracked Output

**RAG Evidence（RAG 证据）**：
围绕既有候选商品检索到、用于回答和推荐解释 grounding 的商品知识证据。
_Avoid_: Recall Candidate、Ranking Signal

**Recommendation Delivery（推荐交付）**：
一次已经向特定 Profile User 返回的有序 Candidate Item 集合，是曝光与后续反馈归因的边界。
_Avoid_: HTTP Request、Agent Turn、Display Product

**Recommendation Feedback Event（推荐反馈事件）**：
Profile User 针对一次 Recommendation Delivery 中某个 Catalog Item 已经发生的不可变语义事实。
_Avoid_: Interaction Record、Mutable Preference、Ranking Command

**Session Preference（会话偏好）**：
由当前 Session 内明确反馈派生、只在该 Session 中强影响排序的临时偏好状态。
_Avoid_: Long-term Memory、Feedback Event

**Profile Preference（画像偏好）**：
以 Profile User 为范围、可跨 Session 使用并允许用户查看和删除的弱偏好状态。
_Avoid_: Account Setting、Session Preference、Raw Feedback

**Preference Version（偏好版本）**：
标识某个 Profile User 的在线偏好投影已经应用到哪次状态变化的单调版本。
_Avoid_: Model Version、Recommendation Request ID

**Feedback Reversal（反馈撤销）**：
引用既有 Recommendation Feedback Event、以新事实抵消其当前偏好影响的事件。
_Avoid_: Event Deletion、History Rewrite
