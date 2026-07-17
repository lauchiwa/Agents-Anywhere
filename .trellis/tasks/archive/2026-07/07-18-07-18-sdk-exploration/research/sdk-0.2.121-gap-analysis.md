# Research: SDK 0.2.119 → 0.2.121 Gap Analysis

- **Query**: 对比 claude-agent-sdk 0.2.119 和 0.2.121，结合连接器现有实现，产出可接入功能清单
- **Scope**: internal (both SDK versions + connector source)
- **Date**: 2026-07-18

---

## 1. 版本差异速览

### 文件级 diff 结果

通过 `diff -rq` 对两版本目录完整对比，只发现以下 4 处差异：

| 文件 | 变化内容 |
|------|---------|
| `_version.py` | `__version__` 从 `0.2.119` → `0.2.121` |
| `_cli_version.py` | `__cli_version__` 从 `2.1.210` → `2.1.212`（捆绑 CLI 版本） |
| `_internal/transport/subprocess_cli.py` | 安全修复：`--resume` 和 `--session-id` 参数传递方式变更 |
| `_bundled/claude` | 捆绑 CLI 二进制升级（2.1.210 → 2.1.212） |

**关键结论：0.2.119 和 0.2.121 的 Python 公开 API 完全相同。** `client.py`、`types.py`、`__init__.py`、`query.py` 及其他所有 `_internal/` 文件（`subprocess_cli.py` 除外）均字节级一致。

### 唯一 Python 代码变更详情

文件：`_internal/transport/subprocess_cli.py` 第 351-361 行

```diff
-   cmd.extend(["--resume", self._options.resume])
+   cmd.append(f"--resume={self._options.resume}")

-   cmd.extend(["--session-id", self._options.session_id])
+   cmd.append(f"--session-id={self._options.session_id}")
```

**原因**：CLI 将 `--resume` 声明为带可选值的 flag。两 token 形式下，以 `-` 开头的 session ID 值会被 CLI 解析器误当作独立 flag，导致参数注入风险。`=` 连接形式保证值始终绑定到该 flag。

这是一个**纯安全修复**，对外部调用者不可见，连接器无需任何适配。

---

## 2. SDK 0.2.121 公开 API 完整清单

以下是 `ClaudeSDKClient` 的所有公开方法（`client.py`，两版本完全相同）：

| 方法 | 签名 | 用途 |
|------|------|------|
| `connect` | `(prompt: str | AsyncIterable | None) -> None` | 连接 Claude，可携带初始 prompt |
| `query` | `(prompt: str | AsyncIterable, session_id: str) -> None` | 发送新消息（流式模式） |
| `receive_messages` | `() -> AsyncIterator[Message]` | 接收所有消息（无限流） |
| `receive_response` | `() -> AsyncIterator[Message]` | 接收到 ResultMessage 为止（单次响应） |
| `interrupt` | `() -> None` | 发送中断信号 |
| `set_permission_mode` | `(mode: PermissionMode) -> None` | 运行时切换权限模式 |
| `set_model` | `(model: str | None) -> None` | 运行时切换模型 |
| `rewind_files` | `(user_message_id: str) -> None` | 回退文件到指定 user message 时刻 |
| `reconnect_mcp_server` | `(server_name: str) -> None` | 重连失败的 MCP 服务器 |
| `toggle_mcp_server` | `(server_name: str, enabled: bool) -> None` | 启用/禁用 MCP 服务器 |
| `stop_task` | `(task_id: str) -> None` | 停止运行中的子任务 |
| `get_mcp_status` | `() -> McpStatusResponse` | 查询所有 MCP 服务器连接状态 |
| `get_context_usage` | `() -> ContextUsageResponse` | 查询 context window 用量 |
| `get_server_info` | `() -> dict | None` | 获取服务器初始化信息（命令/输出样式等） |
| `disconnect` | `() -> None` | 断开连接 |

模块级公开 API（`__init__.py` `__all__`）还包含大量 session 操作（非 ClaudeSDKClient 方法）：

- `rename_session`, `tag_session`, `delete_session`, `fork_session`（及对应 `_via_store` 变体）
- `list_sessions`, `get_session_info`, `get_session_messages`, `list_subagents`, `get_subagent_messages`（及对应 `_from_store` 变体）
- `create_sdk_mcp_server`, `tool`, `SdkMcpTool`（in-process MCP 服务器）

---

## 3. 连接器已实现的 RPC 方法

### ClaudeSdkAdapter 公开方法（`connector/connector/claude/sdk_adapter.py`）

| 方法 | 行号 | 对应 SDK 方法 | RPC 名 |
|------|------|--------------|--------|
| `create_session` | L157 | 无（connector 内部） | `session.create` |
| `sync_session` | L169 | 无（history adapter） | `session.sync` |
| `sync_existing_sessions` | L173 | 无（history adapter） | `session.discover` |
| `start_turn` | L195 | `client.connect` + `client.query` | `turn.start` |
| `interrupt_turn` | L230 | `client.interrupt()` | `turn.interrupt` |
| `set_model` | L246 | `client.set_model()` | `runtime.setModel` |
| `set_permission_mode` | L259 | `client.set_permission_mode()` | `runtime.setPermissionMode` |
| `stop_task` | L273 | `client.stop_task()` | `task.stop` |
| `resolve_approval` | L328 | `can_use_tool` 回调（future 解析） | `approval.resolve` |
| `get_mcp_status` | L348 | `client.get_mcp_status()` | `mcp.status` |
| `rename_session` | L382 | `sdk.rename_session()` | `session.rename` |

### Runtime.py 已处理的 dispatch 方法（`connector/connector/runtime.py`）

| RPC 方法 | 行号 |
|---------|------|
| `session.discover` | L327 |
| `session.create` | L336 |
| `session.sync` | L341 |
| `session.rename` | L346 |
| `turn.start` | L352 |
| `turn.interrupt` | L356 |
| `task.stop` | L358 |
| `approval.resolve` | L360 |
| `runtime.setModel` | L362 |
| `runtime.setPermissionMode` | L362 |
| `mcp.status` | L371 |
| 各 `fs.*`, `shell.*`, `terminal.*`, `capabilities.*` | L384+ |

---

## 4. 未接入功能清单

### 来自 ClaudeSDKClient 的方法

| 方法 | 功能描述 | 远控价值 | 实现难度 |
|------|---------|---------|---------|
| `rewind_files(user_message_id)` | 回退被修改的文件到指定 user message 的时间点，需配合 `enable_file_checkpointing=True` + `extra_args={"replay-user-messages": None}` | 低 | 中（需 options 传 replay-user-messages，且 UserMessage.uuid 须从流中提取并持久化） |
| `reconnect_mcp_server(server_name)` | 对指定 MCP 服务器触发重连；失败时抛异常 | 中 | 简单（3行：取 runtime.client，调方法，包错误） |
| `toggle_mcp_server(server_name, enabled)` | 运行时启用/禁用单个 MCP 服务器；禁用时移除其工具，启用时重连 | 中 | 简单（同 reconnect_mcp_server 实现路径） |
| `get_server_info()` | 返回服务端初始化信息（可用 slash 命令列表、output style 等）；内部读 `_query._initialization_result` | 低 | 简单（1行 getattr） |

### 来自 `__init__.py` 的模块级 API（非 ClaudeSDKClient 方法）

| 方法 | 功能描述 | 远控价值 | 实现难度 |
|------|---------|---------|---------|
| `tag_session(session_id, tags)` | 为会话打标签 | 低 | 简单（透传 SDK 调用） |
| `delete_session(session_id)` | 删除会话 | 中 | 简单（透传，但需确认 safety） |
| `fork_session(session_id, ...)` | 派生会话（分支出新会话 ID） | 低 | 中（需透传 ForkSessionResult） |
| `get_context_usage`（作为 RPC） | 当前 `_capture_context_usage` 在 turn 结束后自动采集并附到 `session.updated` 上；但客户端无法主动按需查询 | 中 | 简单（sdk_adapter 已有内部实现，只需暴露一个 `get_context_usage` public 方法） |
| `get_session_messages` / `list_sessions` 等 history 接口 | 读取历史会话消息 | 中 | 中（history_adapter 已部分实现，需 review 覆盖范围） |

---

## 5. 推荐优先接入项

按「价值/难度」排序：

### P1 — 强烈推荐（高价值 + 低实现成本）

**1. `mcp.reconnect` 和 `mcp.toggleServer` RPC**

- 对应：`client.reconnect_mcp_server()` 和 `client.toggle_mcp_server()`
- 价值：MCP 服务器失连在生产中常见，用户当前必须重启会话。暴露 RPC 后前端可一键修复。
- 难度：**简单**。实现模式与 `stop_task` 完全一致：
  1. 在 `ClaudeSdkAdapter` 新增两个方法，内部 `getattr(runtime.client, "reconnect_mcp_server")(server_name)` 即可
  2. 在 `runtime.py` `dispatch()` 添加两个 `if method == "mcp.reconnect"` 分支
- 参考行：`sdk_adapter.py` L273-294（`stop_task` 实现）

**2. `get_context_usage` 主动查询 RPC**

- 对应：`client.get_context_usage()`
- 价值：`_capture_context_usage`（sdk_adapter.py L916）已在 turn 结束时采集并挂在 `session.updated`，但客户端在 turn 进行中无法查询。暴露为独立 RPC 后，前端可随时拉取当前 context 占用比，在接近上限时提前警告用户。
- 难度：**简单**。`sdk_adapter` 已有 `_capture_context_usage` 私有方法，只需新增：
  ```python
  async def get_context_usage(self, params):
      runtime = self._sessions.get(params.get("sessionId"))
      if runtime is None or runtime.client is None:
          return {}
      getter = getattr(runtime.client, "get_context_usage", None)
      if not callable(getter):
          return {}
      raw = await getter()
      return _context_usage_from_response(raw) or {}
  ```
  然后在 `runtime.py` 添加 `if method == "context.usage"` 分支。

### P2 — 可选（中价值，按需接入）

**3. `mcp.reconnect` 先于 `mcp.toggleServer` 实现**

两者代码量近似，但重连比禁用/启用在实际场景中更常用，建议先做 reconnect。

**4. `delete_session` RPC**

- 对应：`sdk.delete_session()`（模块级函数，非 ClaudeSDKClient 方法）
- 价值：前端目前无法从连接器侧删除历史会话，只能靠 Claude CLI 本地操作
- 难度：中。需注意：`delete_session` 操作本地文件系统，需做权限/路径校验

### P3 — 暂不建议

**5. `rewind_files`**

- 需要在 `ClaudeAgentOptions` 传入 `enable_file_checkpointing=True` + `extra_args={"replay-user-messages": None}`，并从 `receive_response()` 流中持久化每条 `UserMessage.uuid`——这意味着连接器必须维护一个 turn 内的 UUID 列表并暴露给前端。实现链条较长，当前业务场景没有强需求。

**6. `get_server_info`**

- 返回 CLI 初始化信息（slash 命令列表）。远程控制场景没有明显用途；信息已经在 initialize 阶段获取，不需要单独 RPC。

---

## Caveats / Not Found

1. **两版本公开 API 完全相同**：本次升级（0.2.119 → 0.2.121）是纯 bugfix 发布，没有新增任何 Python API 方法或类型。差距分析中「未接入项」均来自 0.2.119 就已有的 API，不是 0.2.121 新增。

2. **捆绑 CLI 版本差异**（2.1.210 → 2.1.212）：CLI 本身可能有新功能，但这些功能只能通过已有的 SDK API 间接访问，对连接器的接入工作没有额外影响。

3. **server/agent_server/claude/sdk_driver.py 未检查**：任务要求检查的是连接器侧，服务端 SDK driver 未纳入本次分析范围。

4. **SessionStore 相关 API**（`list_sessions_from_store` 等）：SDK 提供了完整的 SessionStore 抽象，但连接器当前通过 `ClaudeHistoryAdapter`（同步到服务端 DB）管理历史，与 SDK 的 SessionStore 机制是并行路径，不建议混用。
