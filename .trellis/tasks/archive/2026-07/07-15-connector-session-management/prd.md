# 会话管理 rename / fork / delete / list

## Goal

SDK 提供一整套会话管理：`rename_session` / `fork_session` / `delete_session` / `list_sessions` / `get_session_info` / `get_session_messages` 等（含 `_via_store` 异步变体、`ForkSessionResult`）。连接器目前只能只读地从磁盘读取标题（history 同步时读 custom_title/summary），不能改名、不能分叉、不能删除。

## Background（调研结论）

- 变更类：`fork_session` / `rename_session` / `tag_session` / `delete_session`。
- 查询类：`list_sessions` / `get_session_info` / `get_session_messages` / `list_subagents` / `get_subagent_messages`。
- SessionStore 抽象与 option 侧 `session_store` / `fork_session` 等。
- 连接器现有 RPC 只有 create/sync/start_turn/interrupt/resolve_approval，无任何会话管理写操作。

## Requirements

- 分阶段：先做高价值的 rename 与 delete，再评估 fork（分叉涉及 externalSessionId 派生与时间线复制，复杂度高）。
- 新增对应连接器 RPC，服务端透传，客户端提供入口（会话列表的重命名/删除菜单）。
- 与服务端已有的 session 表/状态保持一致（改名要同步 DB 里的标题）。
- 删除需二次确认（破坏性操作），并明确是否连带清理磁盘 transcript。

## Acceptance Criteria

- [ ] 可对会话改名，web/Android 与服务端标题一致。
- [ ] 可删除会话（带确认），状态正确。
- [ ] fork 若纳入本任务：分叉出的新会话可独立继续，不影响原会话。
- [ ] 相关 RPC 有连接器 + 服务端测试覆盖。

## Notes

- 优先级 P3。
- 建议拆成 rename/delete（先做）与 fork（后做）两个子任务，视工作量。
- delete 是破坏性操作，设计阶段确认清理边界。
