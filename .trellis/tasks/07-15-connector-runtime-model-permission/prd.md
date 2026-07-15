# turn 中途切换 model / permission_mode

## Goal

SDK 提供运行时方法 `client.set_model()` 与 `client.set_permission_mode()`，可在对话进行中切换。连接器只在 `start_turn` 通过 params 一次性传入 `model`/`permissionMode`（sdk_adapter.py `_options_kwargs`:609），turn 中途改不了——用户想临时切模型或放宽/收紧权限必须新开一轮。

## Background（调研结论）

- `_options_kwargs` 把 `model` / `permission_mode` / `effort` 作为启动选项传入，之后无法变更。
- SDK client 暴露 `set_model(model)` 和 `set_permission_mode(mode)` 控制协议方法。
- 需要新增连接器 RPC 方法，并把 runtime 持有的 client 引用暴露给这些调用。

## Requirements

- 新增连接器 RPC：`set_model` / `set_permission_mode`，作用于当前 session 的活动 client。
- 无活动 client 时给出明确失败（reason），不崩溃。
- 服务端透传新 RPC；客户端提供切换入口（模型选择器 / 权限模式切换）。
- 切换后的值对后续 turn 生效，并正确反映在 session 状态里。

## Acceptance Criteria

- [ ] 对话进行中可切换 model 与 permission_mode 并生效。
- [ ] 无活动 client 时返回可读失败原因。
- [ ] 服务端与至少一个客户端打通切换入口。
- [ ] 连接器测试覆盖两个新 RPC（含无 client 的降级路径）。

## Notes

- 优先级 P2。
- permission_mode 切换与 plan-mode 任务相关（plan 是其中一个可选值），但本任务只做“运行时可切换”机制。
