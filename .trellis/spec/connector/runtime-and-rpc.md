# 运行时与 RPC

> `BackendRpcClient` 的主循环、RPC 路由、通知批处理与鉴权约定。改动 `runtime.py` 前先读本文件。

## 连接生命周期

`run_forever` 是最外层循环，`run_once` 是单次连接：

- `run_forever` 起一个共享 `httpx.AsyncClient` 和 `_flush_loop`，然后不断 `run_once`，按异常类型决定重连还是退出。
- `run_once` 先拿 access token，连 `/connector/ws`，连上后立即发现并上报 capabilities，再起 `_heartbeat_loop` 和 `_sync_existing_loop` 两个后台任务，然后进入 `async for` 读消息循环。
- 连接断开时（`finally`）取消两个后台任务并清空 `self._ws`。

新增后台任务照 `_heartbeat_loop` / `_sync_existing_loop` 的模式：在 `run_once` 里 `create_task`，在 `finally` 里 `cancel`。

参考文件：`connector/runtime.py` 的 `run_forever` / `run_once`。

## 鉴权失败必须区分「可重试」和「不可重试」

这是主循环最关键的一条规则。`ConnectorAuthenticationError` 表示凭据失效或被吊销，**绝不重试**，直接抛出让进程停下；其他异常（含普通 `ConnectionClosed`）才 sleep 后重连。

- WebSocket 关闭码 `1008` / `4001` 且 reason 含 "connector" → 判定为鉴权关闭（`_is_auth_close`），转成 `ConnectorAuthenticationError`。
- HTTP 401 在鉴权/ingest/文件传输各处的处理是：先 `ensure_access_token(force=True)` 刷新重试一次，仍 401 才抛 `ConnectorAuthenticationError`。

不要把鉴权失败并进「sleep 后重连」的分支——那会对着已吊销的凭据无限重连。

参考文件：`connector/runtime.py` 的 `run_forever` 异常分支、`_is_auth_close`、`authenticate`。

## RPC dispatch 是显式路由表

`handle_message` 只处理 `type == "request"`，调用 `dispatch` 拿结果，用 `send_response` 回 `ok=True/False`。`dispatch` 是一长串 `if method == "..."` 的显式路由：session/turn/approval 类转发到 `_resolve_adapter(params)` 选中的运行时适配器，`fs.*` / `shell.*` / `terminal.*` 转发到 `self.local_ops`，`capabilities.*` 走本地发现。

- 新增 RPC 方法：在 `dispatch` 里加一个分支，未知方法统一 `raise ValueError(f"unsupported connector method: {method}")`。
- 异常回传：`handle_message` 捕获所有异常，取 `getattr(exc, "code", None) or exc.__class__.__name__` 作为 error code 回给后端（见 error-handling.md）。
- 运行时选择：永远通过 `_resolve_adapter(params)`（读 `params["runtime"]`，缺省 `DEFAULT_RUNTIME = "codex"`），不要在分支里直接取 `self.adapters["codex"]`。

参考文件：`connector/runtime.py` 的 `dispatch`、`handle_message`、`_resolve_adapter`。

## 通知走批处理队列，别逐条 POST

流式场景下运行时每个 token 产生一条通知。逐条同步 POST 会让下一条等上一条 round-trip，拖垮吞吐。约定：

- 适配器通过 `send_backend_notification`（即 `notification_sink`）把通知 `put` 进 `_notify_queue`。
- `_flush_loop` 按 `FLUSH_WINDOW_SECONDS`（20ms）窗口或 `FLUSH_MAX`（64 条）批量 `_post_batch`，把 N 条 delta 合并成 1 个 HTTP POST。
- `_post_batch` 前会用 `_coalesce_timeline_item_upserts` 去重：同一 timeline item 在一个批次里只保留最新一条 upsert。
- 已经成批的通知（如 `sync_existing_sessions` 的结果）用 `ingest_notifications` 直接同步发，跳过队列，避免白等一个窗口。

新增高频通知走 `send_backend_notification`（异步入队）；只有一次性大批量结果才用 `ingest_notifications`。

参考文件：`connector/runtime.py` 的 `send_backend_notification`、`_flush_loop`、`_post_batch`、`_coalesce_timeline_item_upserts`。

## 配置与网络

- `ConnectorConfig` 支持三种来源：`from_env`（环境变量）、`load`（JSON 文件，默认 `~/.agent-server/connector.json`）、`from_mapping`。`save` 会把文件权限设成 `0o600`。
- 代理判断：`_is_loopback_url` 为真（127.0.0.1/localhost/::1）时禁用代理并 `trust_env=False`；否则允许系统代理。新建 HTTP client 一律走 `_new_http_client`，不要直接 `httpx.AsyncClient(...)`。
- WebSocket URL 由 `_ws_url` 从 server_url 推导（https→wss，http→ws）。

参考文件：`connector/runtime.py` 的 `ConnectorConfig`、`_new_http_client`、`_is_loopback_url`、`_ws_url`。

## MCP 外部 server 配置（本地文件，不走服务端下发）

### 配置文件契约

MCP 配置独立于 `connector.json`，存放在同目录的 `mcp.json`（默认 `~/.agent-server/mcp.json`，可用 `AGENT_CONNECTOR_MCP_CONFIG` 覆盖），权限 0600 由用户手动编辑。

```json
{
  "servers": {
    "<name>": {
      "type": "stdio",          // stdio | http | sse，缺省 stdio
      "command": "...",         // stdio 必填
      "args": ["..."],          // stdio 可选
      "env": {"KEY": "val"}    // stdio 可选，敏感字段不入日志
    },
    "<name2>": {
      "type": "http",
      "url": "https://...",
      "headers": {"Authorization": "Bearer ..."}  // 敏感字段不入日志
    }
  }
}
```

字段命名与 SDK 类型完全对齐：`McpStdioServerConfig` / `McpHttpServerConfig` / `McpSSEServerConfig`（`claude_agent_sdk/types.py`）。

### 信任边界（关键规则）

**MCP server 配置只能来自连接器本地文件，服务端永远不下发 MCP 配置。**

理由：stdio type 配置等价于"在用户设备上跑这条 shell 命令 + env"，信任边界必须落在执行侧（连接器=用户设备）。服务端若能下发 stdio 命令，一旦服务端被撑破，所有连接器同时 RCE。

- 连接器注入 `strict_mcp_config=True` 配合本地配置，防止 CLI 从系统级 CLAUDE.md 等渠道读取到未声明的 server。
- 未来如需中心化编排，走「本地 allowlist + 服务端只能 enable/disable 已白名单 server」的混合模式，不是直接下发 server 定义。

### 日志脱敏规则

`env` 值、`headers` 值、命令参数（args）**不得出现在任何日志调用**。只记录 server name、type 和连接状态。`McpConfig.load` 加载失败时只打 warning，不含配置内容。

### mcp.status RPC

```
method: "mcp.status"
params: {} 或 {"runtime": "claude"}
```

- 无 `runtime` 字段时默认路由到 claude adapter（MCP 是 Claude only）。
- adapter 上的 `get_mcp_status()` 调用活跃 session 的 `ClaudeSDKClient.get_mcp_status()`，返回 `{"mcpServers": [McpServerStatus, ...]}`（SDK 原样透传，不做字段重命名）。
- adapter 未实现该方法（如 codex）或无活跃 session：返回 `{"mcpServers": []}` 而不是报错。

### 加载失败行为

文件不存在、JSON 错误、顶层 `servers` 不是 dict：均静默返回空 config（`{}`），turn 照常启动，`mcp_servers` / `strict_mcp_config` 不塞进 `ClaudeAgentOptions`。这是零回归的保证。

参考文件：`connector/connector/claude/mcp_config.py`（`McpConfig`）、`sdk_adapter.py:_options_kwargs`、`runtime.py:dispatch` 的 `mcp.status` 分支。
