# plan mode 规划模式接入

## Goal

SDK 的 `PermissionMode` 含 `"plan"`（只规划、不执行工具），是官方常用模式。连接器支持传入 permission_mode，但客户端没有把 "plan" 作为可选模式暴露出来——用户无法让 Claude 先出计划再执行。

## Background（调研结论）

- `PermissionMode = "default" | "acceptEdits" | "plan" | "bypassPermissions" | "dontAsk" | "auto"`（SDK types.py:25）。
- 连接器 `_options_kwargs` 已能透传 `permissionMode`，所以底层通路是通的，缺的是客户端选项与 plan 模式产物（计划）的展示。
- 本地历史里 plan 模式退出通过 attachment `plan_mode_exit` 体现（2 次），说明真实存在这一流程。

## Requirements

- 客户端（web + Android）在权限模式选择里加入 "plan" 选项。
- 评估 plan 模式下的产物如何展示：Claude 产出计划后等待用户确认执行，需要相应的交互（可能复用/扩展 approval 流）。
- 若接入 runtime 切换（见 runtime-model-permission 任务），plan ↔ default 的切换应顺畅。
- 处理 `plan_mode_exit` attachment（若走历史回放）。

## Requirements 依赖

- 建议在 `connector-runtime-model-permission` 之后做（复用其 set_permission_mode 通路），或与之合并评估。

## Acceptance Criteria

- [ ] 用户可选择 plan 模式启动一轮对话。
- [ ] plan 模式下工具不被执行，计划正常呈现。
- [ ] 从 plan 切到执行的路径清晰可用。
- [ ] 相关测试覆盖 permission_mode="plan" 的传递。

## Notes

- 优先级 P2。
- 与 runtime-model-permission 强相关。
