# hooks 业务化利用

## Goal

评估并（按价值）利用 SDK 的 hook 事件体系。当前连接器只注册了一个 `PreToolUse` 空 hook,其唯一目的是"保持权限流打开"(sdk_adapter.py:631 `_keep_permission_stream_open` 只返回 `{"continue_": True}`),10 种 hook 事件的业务价值完全没被利用。

## 背景(调研已确认)

- SDK 0.2.116 的 `HookEvent` 共 10 种(types.py:260):PreToolUse / PostToolUse / PostToolUseFailure / UserPromptSubmit / Stop / SubagentStop / PreCompact / Notification / SubagentStart / PermissionRequest。
- 每种有强类型 input(`PreToolUseHookInput` 等),`ClaudeAgentOptions.include_hook_events` 可把 hook 事件当消息流回来(`HookEventMessage`)。
- 潜在业务价值举例:
  - `PostToolUseFailure` —— 工具失败可结构化上报,改善错误展示。
  - `SubagentStart` / `SubagentStop` —— 子代理生命周期,配合子代理进度事件任务([[07-15-connector-subagent-progress-events]])。
  - `PreCompact` —— 压缩前钩子,配合压缩边界任务([[07-15-connector-compact-boundary]])。
  - `Notification` —— 系统通知(如需要用户注意),可推送到客户端。

## Requirements

- 先做价值评估:列出 10 种 hook 里哪些对 Agents-Anywhere 有实际收益,哪些无关。
- 对选中的 hook,给出具体用途与产出(时间线项 / 通知 / 结构化上报)。
- 保证现有 `_keep_permission_stream_open` 的权限流打开行为不被破坏(这是审批机制的前提)。
- 明确与其它任务的边界:SubagentStart/Stop 与子代理进度任务、PreCompact 与压缩边界任务可能重叠,需协调归属避免重复实现。

## Acceptance Criteria

- [ ] 产出一份 hook 价值评估(哪些做、哪些不做、为什么)。
- [ ] 至少落地 1 个有明确用户价值的 hook(建议 PostToolUseFailure 或 Notification)。
- [ ] 现有权限流行为无回归,审批仍正常工作。
- [ ] 连接器测试通过。

## Notes

- 优先级 P3。属于"能做很多但未必都值得"的探索型任务,建议先评估后动手。
- 关联梯队:第四梯队(高级特性)。
- 与 [[07-15-connector-subagent-progress-events]] 和 [[07-15-connector-compact-boundary]] 有交集,实现前先对齐。
