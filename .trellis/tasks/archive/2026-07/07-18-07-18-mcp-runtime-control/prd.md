# MCP 运行时控制 + context.usage 主动查询 RPC

## 背景

SDK 0.2.121 已有三个 ClaudeSDKClient 方法未在连接器中暴露为 RPC：
- `reconnect_mcp_server(server_name)` — 重连失败的 MCP 服务器
- `toggle_mcp_server(server_name, enabled)` — 运行时启用/禁用 MCP 服务器
- `get_context_usage()` — 主动查询 context window 占用

三者实现模式与已有 `stop_task` 完全一致，改动范围：connector sdk_adapter + runtime + server API + web api.ts。

## Requirements

1. **`mcp.reconnect` RPC**：客户端发送 `{method: "mcp.reconnect", sessionId, serverName}`，连接器调 `client.reconnect_mcp_server(serverName)`，返回 `{ok, reason?}`。
2. **`mcp.toggleServer` RPC**：客户端发送 `{method: "mcp.toggleServer", sessionId, serverName, enabled}`，连接器调 `client.toggle_mcp_server(serverName, enabled)`，返回 `{ok, reason?}`。
3. **`context.usage` RPC**：客户端发送 `{method: "context.usage", sessionId}`，连接器调 `client.get_context_usage()`，返回结构化用量数据。
4. 服务端新增三个对应 API 端点（参照 `sessions.py` 中 `stop_task` 端点模式）。
5. Web `api.ts` 新增三个对应方法（参照 `stopTask()` 模式）。
6. 三个功能均有单元测试覆盖（connector 测试，参照 `test_stop_task_rpc_calls_client_stop_task`）。

## Acceptance Criteria

- [ ] `connector/tests/test_claude_sdk_adapter.py` 新增测试：`test_mcp_reconnect_rpc`、`test_mcp_toggle_server_rpc`、`test_context_usage_rpc`，全部通过。
- [ ] `cd connector && uv run pytest` 全部通过。
- [ ] `cd server && uv run pytest` 全部通过（如有 server 测试新增则也通过）。
- [ ] `cd web-next && npx tsc --noEmit` 零错误。

## 范围外

- Web UI（前端调用入口）本任务暂不做，只加 api.ts 方法
- Android 端接入
- MCP 状态订阅推送（已有 `mcp.status` RPC）
