# approved_for_session 持久化免批

## Goal

`_can_use_tool`（sdk_adapter.py:637）识别 `approved_for_session` 状态并放行，但**没有任何持久化**——同一工具下次调用仍会重新弹审批。"本会话批准一次、后续免批"这个能力实际未实现；`PermissionResultAllow.updated_permissions` 也从未使用。

## Background（调研结论）

- `resolve_approval` 接受 status，`_can_use_tool` 对 `approved` 与 `approved_for_session` 都放行，但两者行为完全相同——后者不记忆。
- SDK 提供 `PermissionResultAllow.updated_permissions: list[PermissionUpdate]` 与 `PermissionUpdate`（rules/behavior/mode/directories/destination）可用于持久化放行规则。
- 客户端 choices 已含 `approve_for_session`（web PermissionCard 有对应按钮）。

## Requirements

- 在 runtime 维护一个 session 级已批准工具/规则集合（键的粒度需定义：按 tool_name？按 tool_name+关键参数？）。
- 命中已批准规则时，`_can_use_tool` 直接放行而不发 `approval.requested`。
- 评估是否改用 `PermissionResultAllow.updated_permissions` 让 CLI 侧自行记忆（更贴近原生语义）。
- session 结束/turn 生命周期结束时的清理策略需明确（"session" 的边界）。

## Acceptance Criteria

- [ ] 同一工具 `approved_for_session` 后，本会话内后续调用不再弹审批。
- [ ] 放行粒度有明确、安全的定义（避免过宽放行带来风险）。
- [ ] 新 session / 重启后不复用旧的 session 级放行。
- [ ] 连接器测试覆盖：首次弹审批 → 批准 for session → 二次自动放行。

## Notes

- 优先级 P2。
- 安全敏感：放行粒度定义不当会让"批准一次"变成"永久放行任意参数"，设计阶段需重点评审。
