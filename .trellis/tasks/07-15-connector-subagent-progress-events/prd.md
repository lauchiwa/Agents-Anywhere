# 子代理进度事件（TaskStarted/Progress/Updated/Notification）

## Goal

四类 Task 结构化进度消息（`TaskStartedMessage` / `TaskProgressMessage` / `TaskUpdatedMessage` / `TaskNotificationMessage`）被 `_receive_response` 的 `system_cls` 分支无条件跳过（sdk_adapter.py:325-328），子代理运行过程不可见，用户只能等最终输出。

## 背景 / 现状

- `_receive_response`（sdk_adapter.py:304-333）对 `system_cls` 消息一律 `continue` 跳过，注释写着 "System messages (init, task progress, etc.) are not part of the user-facing timeline"。
- 连接器已支持子代理**输出**的父子嵌套：`normalizers.py` 读 `parent_tool_use_id`，reducer 用它把子代理 text/tool 挂到父 Task 卡片下（见 `test_claude_subagent_output_is_linked_to_parent_task_item`）。
- 缺的是"子代理正在做什么"的**结构化进度**——TaskStarted/Progress 等。
- 本地历史实证:本 CLI 变体子代理工具名是 `Agent`（带 `subagent_type`），`isSidechain=true` 消息 1205 条；进度信息可能也经 attachment（`agent_listing_delta` 等）承载，需实测确认进度事件的真实落地形态。
- SDK 类型：`TaskUsage`、`TaskNotificationStatus`、`TaskUpdatedStatus`、`TERMINAL_TASK_STATUSES` 可用。

## Requirements

- 在 `_receive_response` 增加对四类 Task 消息的识别（类名匹配，与现有 `_is_result_message` 风格一致）。
- 决定呈现形态：是更新父 Task 卡片的 status/进度文本，还是产出独立的 system 进度项。倾向前者（挂在已有 Task 卡片上，复用父子嵌套）。
- 归一化 + reduce 管线打通，实时与历史同源。
- 确认三层客户端如何展示子代理进度（可能需要下游改动）。

## Acceptance Criteria

- [ ] 先实测：抓取一次真实子代理运行的原始 SDK 消息流，确认 TaskStarted/Progress 等的真实结构与字段。
- [ ] 四类进度消息不再被静默丢弃，转成时间线可消费的数据。
- [ ] 子代理进度关联到正确的父 Task/Agent 卡片。
- [ ] 新增测试覆盖进度消息的归一化与归属。
- [ ] 连接器完整测试套件全绿。

## Notes

- 依赖真实数据：动手前必须先抓一次子代理运行的原始消息流（生产日志或本地复现），不要凭 SDK 类型定义猜字段。
- 优先级 P1（内容层缺口，配合已有父子卡片嵌套价值高）。
