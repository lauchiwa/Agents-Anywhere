# context/token 用量展示

## Goal

SDK 提供 `get_context_usage()`（对应 CLI `/context`），且每条 `ResultMessage` 都带 `usage`/`cost` 字段。连接器 `_result_message_to_raw`（sdk_adapter.py）当前只取 `result` 文本和 `subtype`，用量信息全部丢弃——用户无法感知上下文将满、也看不到本轮 token/成本消耗。

## Background（调研结论）

- `ResultMessage` 携带 `usage`（input/output/cache tokens）与 `total_cost_usd` 等字段；`_result_message_to_raw` 只 `_extract_attr(message, "result")`，其余丢弃。
- SDK `ClaudeSDKClient.get_context_usage()` 返回 `ContextUsageResponse`：`categories`（名/tokens/color/isDeferred）、`totalTokens`、`maxTokens`、`percentage`、`model`、`isAutoCompactEnabled`、`autoCompactThreshold` 等。
- 下游没有现成 UI（不同于 thinking），需要新增展示位。

## Requirements

- 解析 `ResultMessage.usage` / `total_cost_usd`，在 turn 结束（`turn.end` 或独立 system 项）携带本轮 token 用量与成本。
- 评估是否新增一个 RPC 方法暴露 `get_context_usage()`，供客户端主动查询“当前上下文占用/是否接近 autocompact”。
- 客户端（web + Android）新增用量展示位：至少显示总 token / 上限 / 百分比；成本可选。
- 历史回放路径若能从 transcript 拿到 usage，也应一致呈现（无则跳过，不报错）。

## Acceptance Criteria

- [ ] `ResultMessage` 的 usage/cost 被解析并随 turn 结束下发，不再丢弃。
- [ ] 新增（或复用）时间线/状态字段承载用量，服务端不报错。
- [ ] web 与 Android 至少能显示总 token 与占上限百分比。
- [ ] 无 usage 数据时优雅降级，不产生空卡片或异常。
- [ ] 连接器测试覆盖 usage 解析；服务端全套测试通过。

## Notes

- 优先级 P2：数据大部分现成（ResultMessage 已带），主要成本在下游展示位。
- `get_context_usage()` 是运行时 RPC，需 client 处于活动状态，注意与 turn 生命周期的关系。
