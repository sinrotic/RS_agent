---
name: a2ui-interface
description: 当购物对话需要交互式需求表单、动态商品布局、快捷追问按钮，或调整已有界面的组件和展示数据时加载。普通文字解释继续使用 text；商品事实与候选集合由推荐和目录工具提供。
---

# 购物界面生成与更新

使用服务端附加的组件目录和消息 Schema 生成 A2UI v0.9 消息。目录 ID 为 `urn:rs-agent:a2ui:shopping:v1`，它是本应用的购物目录，不是 Google Basic Catalog。

## 输出流程

1. 获取当前任务需要的业务证据。`ProductCards.itemIds` 只引用本轮推荐结果或工具实际返回的 Catalog Item；商品标题、价格和图片由前端目录 hydration 提供。
2. 新界面先发送 `createSurface`，再发送 `updateComponents` 和所需的 `updateDataModel`。界面树根组件 ID 固定为 `root`，所有子组件 ID 都应存在，结构保持无环。
3. 需要渐进展示或在工具处理期间修改界面时调用 `emit_ui`，参数为 `{"messages":[...]}`。成功后继续处理任务；失败时根据工具反馈修正消息。
4. 已创建的界面沿用 `surfaceId`，用 `updateComponents` 替换指定 ID 的组件，用 `updateDataModel` 替换指定路径的值。省略 `value` 表示删除该路径；省略 `path` 或使用 `/` 表示整个数据模型。
5. 当前前端支持的界面与状态会通过 `context.a2ui_state` 回传，可据此更新已有界面。已有 surface 要先删除再重建；新 surface 使用不重复的 ID。替换过时界面时发送 `deleteSurface`。
6. 用 `emit_final_answer` 完成本轮。可在 `a2ui` block 的 `messages` 中提交尚未发布的消息；已通过 `emit_ui` 发布的消息只发布一次。保留一段简短中文 `text` 作为界面加载失败时的回答。

## 组件和交互

- `Column` / `Row` 用 `children` 引用子组件；`Card` 用 `child` 引用子组件。
- `Text.text` 可以是文字，或 `{"path":"/summary"}` 数据绑定。
- `ProductCards` 使用 `itemIds` 和可选的 `layout: "grid" | "list"`，复用已有商品卡片和反馈按钮。
- `TextField` 的 `value` 使用可写路径绑定，`label` 是中文字段名。输入仅在用户点击提交后回传。
- `Button.child` 引用文字组件；`action.event.name` 使用 `submit_query`，`action.event.context.query` 为用户确认提交的查询文字或绑定值。
- 使用数据模型存放用户可见内容和表单值，使用绝对 JSON Pointer 路径。组件目录以服务端附加的 Schema 为准。

## 表单示例

以下是 `emit_ui` 的参数；用户填写需求并点击按钮后，前端将查询作为下一条用户消息提交。

```json
{
  "messages": [
    {"version":"v0.9","createSurface":{"surfaceId":"need-form-1","catalogId":"urn:rs-agent:a2ui:shopping:v1"}},
    {"version":"v0.9","updateComponents":{"surfaceId":"need-form-1","components":[
      {"id":"root","component":"Column","children":["need","submit"]},
      {"id":"need","component":"TextField","label":"您想找什么商品？","value":{"path":"/query"}},
      {"id":"submit-label","component":"Text","text":"按这些条件查找"},
      {"id":"submit","component":"Button","child":"submit-label","action":{"event":{"name":"submit_query","context":{"query":{"path":"/query"}}}}}
    ]}},
    {"version":"v0.9","updateDataModel":{"surfaceId":"need-form-1","value":{"query":""}}}
  ]
}
```

最终答案参数仍包含有序 `blocks`。`a2ui` block 的 `content`、`card_set_id`、`item_ids`、`layout` 使用 null；其他 block 的 `messages` 使用 null。

完成条件：所需消息已成功发布，用户操作有对应事件，且 `emit_final_answer` 已给出基于证据的中文回答。界面数据仅包含用户可见信息；商品事实以工具证据为准。
