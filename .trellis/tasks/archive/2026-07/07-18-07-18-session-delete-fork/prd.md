# session.delete / session.fork RPC

## 背景

SDK 提供 `delete_session(session_id, directory?)` 和 `fork_session(session_id, directory?, up_to_message_id?, title?)` 两个模块级函数。
连接器已有 `rename_session` 作为完全对标的参考实现（同步文件系统操作，传 `externalSessionId` + `cwd`）。

## Requirements

1. **`session.delete` RPC**：客户端传 `{externalSessionId, cwd?}`，连接器调 `sdk.delete_session(externalSessionId, directory=cwd)`，返回 `{ok, reason?}`。
   - `delete_session` 是**硬删除**（删除本地 JSONL 文件），不可逆。接口层无需额外确认，由调用方负责。
2. **`session.fork` RPC**：客户端传 `{externalSessionId, cwd?, upToMessageId?, title?}`，连接器调 `sdk.fork_session(...)`, 返回 `{ok, sessionId: <新 UUID>}`。
3. 服务端新增对应 API 端点（参照 `sessions.py` 中已有的 `session.rename` 端点）。
4. Web `api.ts` 新增两个对应方法。
5. 两个功能均有单元测试。

## Acceptance Criteria

- [ ] `connector/tests/test_claude_sdk_adapter.py` 新增：`test_delete_session_rpc` 、`test_fork_session_rpc`，全部通过。
- [ ] `cd connector && uv run pytest` 全部通过。
- [ ] `cd server && uv run pytest` 全部通过。
- [ ] `cd web-next && npx tsc --noEmit` 零错误。

## 范围外

- Web UI（列表页删除按钮、fork 入口）本任务暂不做，只加 api.ts 方法
- Android 端接入
- `tag_session` RPC（P3，价值低，可单独处理）
