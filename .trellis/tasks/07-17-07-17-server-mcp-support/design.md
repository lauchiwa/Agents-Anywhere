# Design: 服务端 MCP 支持

## 架构决策

### 为何不走 runtime_settings 体系

`runtime_settings` 有固定 schema（`RuntimeConfigField` 只支持 string/enum/boolean/object/number，object 需声明子字段），无法承载自由命名的 `{serverName: {type, command/url, ...}}` 结构。`normalize_runtime_settings` 和 `filter_runtime_settings` 会丢弃未声明的 key（历史上 `add_dirs` 栽在这里过）。

MCP 服务器配置走独立 JSON blob 列 + 专用 API，与 runtime_settings 体系完全解耦。

### 存储层

两张表各加一列：

```
connectors.mcp_servers_json  TEXT  -- nullable，JSON object {serverName: config}
sessions.mcp_servers_json    TEXT  -- nullable，JSON object {serverName: config}
```

迁移：`_ensure_compat_schema_async` + `_ensure_compat_schema_sync`（均在 `engine.py`），使用 `_column_exists_*` 守卫的 `ALTER TABLE ... ADD COLUMN` —— 与 `context_usage_json`/`rate_limit_json` 完全同构，无破坏性。

`schema.py` 中的 `connectors` 和 `sessions` Table 声明也同步加列（供类型系统和未来 `create_all` 使用）。

### 清洗函数：`sanitize_mcp_servers`

放在 `server/agent_server/core/runtime_config.py`，与 connector 侧 `mcp_config.py` 的校验规则对齐：

```
_STDIO_KEYS = {"type", "command", "args", "env"}
_HTTP_KEYS  = {"type", "url", "headers"}
_SSE_KEYS   = {"type", "url", "headers"}
```

- 入参不是 `dict` → `ValueError("mcpServers must be an object")`
- server 名不是非空字符串 → `ValueError`
- `type` 不在 `{stdio, http, sse}` → `ValueError`（`sdk` 类型明确拒绝）
- 未知 key → `ValueError`
- `stdio` 缺 `command` 或 `command` 非字符串 → `ValueError`
- `http`/`sse` 缺 `url` 或 `url` 非字符串 → `ValueError`
- 通过后返回清洗后的副本（去掉无效可选字段，保留合法可选字段）

### 合并函数：`merge_mcp_servers`

```python
def merge_mcp_servers(
    connector: dict | None,
    session: dict | None,
) -> dict:
    return {**(connector or {}), **(session or {})}
```

语义：session 中出现的同名 server **整体替换** connector 配置（不是字段级 merge）。结果为空 dict 时调用方省略注入。

### 存取层：`McpServersRepositoryMixin`

新建 `server/agent_server/infra/repositories/mcp_servers.py`，Mixin 风格与现有 mixin 一致：

```python
class McpServersRepositoryMixin:
    async def get_connector_mcp_servers(self, connector_id: str) -> dict | None
    async def set_connector_mcp_servers(self, connector_id: str, servers: dict) -> None
    async def get_session_mcp_servers(self, session_id: str) -> dict | None
    async def set_session_mcp_servers(self, session_id: str, servers: dict) -> None
    async def get_effective_mcp_servers(
        self, session_id: str, connector_id: str
    ) -> dict  # 合并后，空 dict 表示无配置
```

实现直接 `UPDATE connectors/sessions SET mcp_servers_json = :v WHERE id = :id`，读取做 `_json_loads` + `isinstance(raw, dict)` 守卫。

### facade 层

在 `runtime_config_facade.py` 加对应的 5 个 facade 方法，通过 `self.runtime_config` 委托（与现有模式一致）。

实际上 `Store` 继承了所有 Mixin，只需 `McpServersRepositoryMixin` 加进 `Store` 的基类列表即可。

### API 层

在 `server/agent_server/api/connectors.py` 加 4 个端点：

```
GET  /api/connectors/{connector_id}/mcp-servers
PUT  /api/connectors/{connector_id}/mcp-servers
GET  /api/sessions/{session_id}/mcp-servers
PUT  /api/sessions/{session_id}/mcp-servers
```

请求体（PUT）：`{"mcpServers": {...}}`  
响应体（GET/PUT）：`{"mcpServers": {...}}`

权限：GET/PUT connectors endpoint 需校验 connector.userId == current_user.id；sessions endpoint 需校验 session owner。

PUT 流程：
1. 取出 `body["mcpServers"]`（不存在则 422）
2. `sanitize_mcp_servers(raw)` → 失败返回 400 with detail
3. `store.set_connector/session_mcp_servers(id, sanitized)`
4. 返回 `{"mcpServers": sanitized}`

### turn.start 注入

在 `session_run.py` `send_message` 方法的 params 组装段（第 189-213 行附近）加注入：

```python
if session.runtime == "claude":
    try:
        effective_mcp = await self._store.get_effective_mcp_servers(
            session_id, session.connectorId
        )
        if effective_mcp:
            params["mcpServers"] = effective_mcp
    except Exception:
        logger.warning("failed to load mcp servers for turn; continuing without mcp config")
```

条件：仅对 `claude` runtime 注入（connector 侧 MCP 是 Claude-only 能力，Codex 不处理 `mcpServers` 字段）。失败时降级（不抛出，不阻断 turn）。

### 数据流

```
用户 PUT /api/connectors/{id}/mcp-servers
  → sanitize_mcp_servers
  → connectors.mcp_servers_json (DB)

send_message (turn.start)
  → get_effective_mcp_servers
      → get_connector_mcp_servers → connectors.mcp_servers_json
      → get_session_mcp_servers   → sessions.mcp_servers_json
      → merge_mcp_servers
  → params["mcpServers"] = merged (非空时)
  → manager.request(connector_id, "turn.start", params)
      → connector runtime._options_kwargs 读取 mcpServers → 注入 SDK
```

### 凭证策略

与 connector 侧一致：`env`/`headers` 明文存储、完整回显（配置需可见）。日志中不打印 `mcpServers` 内容（API 日志不打印请求体，`logger.warning` 不含配置值）。

## 文件改动范围

| 文件 | 改动 |
|------|------|
| `server/agent_server/infra/db/schema.py` | `connectors` + `sessions` 各加 `mcp_servers_json` 列 |
| `server/agent_server/infra/db/engine.py` | `_ensure_compat_schema_async` + `_sync` 各加 2 行 ALTER |
| `server/agent_server/core/runtime_config.py` | 加 `sanitize_mcp_servers` + `merge_mcp_servers` |
| `server/agent_server/infra/repositories/mcp_servers.py` | 新建 `McpServersRepositoryMixin`（5 方法） |
| `server/agent_server/infra/repositories/runtime_config_facade.py` | 加 5 个 facade 方法（委托给 mcp_servers mixin） |
| `server/agent_server/infra/repositories/facade.py` | `Store` 继承列表加 `McpServersRepositoryMixin` |
| `server/agent_server/core/models.py` | 加 `McpServersResponse` + `McpServersPutRequest` pydantic 模型 |
| `server/agent_server/api/connectors.py` | 加 4 个端点 |
| `server/agent_server/services/session_run.py` | `send_message` 加 MCP 注入段 |
| `server/tests/test_backend_mvp.py` | 加 round-trip + 合并 + 降级 + 拒绝非法配置 测试 |
