# Implementation Plan: 服务端 MCP 支持

## 前置检查

- [ ] 运行 `cd server && python -m pytest tests/ -q` 确认基线通过（预期 ~208 passed）
- [ ] 确认 `server/agent_server/infra/db/engine.py` 中 `_ensure_compat_schema_async` 和 `_ensure_compat_schema_sync` 的位置（当前 L206 / L231）

---

## Step 1：DB Schema — 加列声明

**文件**：`server/agent_server/infra/db/schema.py`

在 `connectors` Table（L18）末尾加：
```python
Column("mcp_servers_json", Text),
```

在 `sessions` Table（L~220）末尾加：
```python
Column("mcp_servers_json", Text),
```

验证：`python3 -c "from agent_server.infra.db.schema import connectors, sessions; print([c.name for c in connectors.c])"` 含 `mcp_servers_json`。

---

## Step 2：DB Migration — ensure_compat_schema

**文件**：`server/agent_server/infra/db/engine.py`

`_ensure_compat_schema_async`（L206）在现有 `rate_limit_json` 块后追加：
```python
if not await _column_exists_async(conn, "connectors", "mcp_servers_json"):
    await conn.execute(text("ALTER TABLE connectors ADD COLUMN mcp_servers_json TEXT"))
if not await _column_exists_async(conn, "sessions", "mcp_servers_json"):
    await conn.execute(text("ALTER TABLE sessions ADD COLUMN mcp_servers_json TEXT"))
```

`_ensure_compat_schema_sync`（L231）同理加 2 行 sync 版本。

验证：启动服务后 `PRAGMA table_info(connectors)` 和 `PRAGMA table_info(sessions)` 含 `mcp_servers_json`。

---

## Step 3：清洗与合并函数

**文件**：`server/agent_server/core/runtime_config.py`

在文件末尾追加（不改动现有函数）：

```python
_MCP_STDIO_KEYS = {"type", "command", "args", "env"}
_MCP_HTTP_KEYS = {"type", "url", "headers"}
_MCP_SSE_KEYS = {"type", "url", "headers"}


def sanitize_mcp_servers(raw: Any) -> dict[str, Any]:
    """Validate and sanitize an mcpServers dict. Raises ValueError on bad input."""
    if not isinstance(raw, dict):
        raise ValueError("mcpServers must be an object")
    result: dict[str, Any] = {}
    for name, cfg in raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"mcp server name must be a non-empty string, got {name!r}")
        if not isinstance(cfg, dict):
            raise ValueError(f"mcp server {name!r} config must be an object")
        server_type = cfg.get("type", "stdio")
        if not isinstance(server_type, str):
            raise ValueError(f"mcp server {name!r} type must be a string")
        if server_type == "sdk":
            raise ValueError(f"mcp server {name!r} type 'sdk' is not supported via API")
        if server_type == "stdio":
            result[name] = _sanitize_mcp_stdio(name, cfg)
        elif server_type in ("http", "sse"):
            result[name] = _sanitize_mcp_url(name, cfg, server_type)
        else:
            raise ValueError(
                f"mcp server {name!r} has unsupported type {server_type!r} "
                f"(expected stdio/http/sse)"
            )
    return result


def _sanitize_mcp_stdio(name: str, cfg: dict[str, Any]) -> dict[str, Any]:
    unknown = set(cfg) - _MCP_STDIO_KEYS
    if unknown:
        raise ValueError(f"mcp stdio server {name!r} has unknown keys: {sorted(unknown)}")
    command = cfg.get("command")
    if not isinstance(command, str) or not command:
        raise ValueError(f"mcp stdio server {name!r} requires a non-empty 'command' string")
    validated: dict[str, Any] = {"type": "stdio", "command": command}
    args = cfg.get("args")
    if args is not None:
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError(f"mcp stdio server {name!r} 'args' must be a list of strings")
        validated["args"] = list(args)
    env = cfg.get("env")
    if env is not None:
        if not isinstance(env, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in env.items()
        ):
            raise ValueError(f"mcp stdio server {name!r} 'env' must be string->string")
        validated["env"] = dict(env)
    return validated


def _sanitize_mcp_url(name: str, cfg: dict[str, Any], kind: str) -> dict[str, Any]:
    allowed = _MCP_HTTP_KEYS if kind == "http" else _MCP_SSE_KEYS
    unknown = set(cfg) - allowed
    if unknown:
        raise ValueError(f"mcp {kind} server {name!r} has unknown keys: {sorted(unknown)}")
    url = cfg.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError(f"mcp {kind} server {name!r} requires a non-empty 'url' string")
    validated: dict[str, Any] = {"type": kind, "url": url}
    headers = cfg.get("headers")
    if headers is not None:
        if not isinstance(headers, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
        ):
            raise ValueError(f"mcp {kind} server {name!r} 'headers' must be string->string")
        validated["headers"] = dict(headers)
    return validated


def merge_mcp_servers(
    connector: dict[str, Any] | None,
    session: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge connector-level and session-level MCP configs. Session wins by name."""
    return {**(connector or {}), **(session or {})}
```

验证：`python3 -c "from agent_server.core.runtime_config import sanitize_mcp_servers; sanitize_mcp_servers({'s': {'type':'sdk','command':'x'}})"` 应抛 `ValueError`。

---

## Step 4：存取 Mixin

**文件**：`server/agent_server/infra/repositories/mcp_servers.py`（新建）

```python
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from agent_server.infra.repositories.store_support import _json_dumps, _json_loads


class McpServersRepositoryMixin:
    async def get_connector_mcp_servers(self, connector_id: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT mcp_servers_json FROM connectors WHERE id = :id"),
                    {"id": connector_id},
                )
            ).one_or_none()
        if row is None:
            return None
        raw = _json_loads(row[0])
        return raw if isinstance(raw, dict) else None

    async def set_connector_mcp_servers(
        self, connector_id: str, servers: dict[str, Any]
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE connectors SET mcp_servers_json = :v WHERE id = :id"
                ),
                {"v": _json_dumps(servers), "id": connector_id},
            )

    async def get_session_mcp_servers(self, session_id: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT mcp_servers_json FROM sessions WHERE id = :id"),
                    {"id": session_id},
                )
            ).one_or_none()
        if row is None:
            return None
        raw = _json_loads(row[0])
        return raw if isinstance(raw, dict) else None

    async def set_session_mcp_servers(
        self, session_id: str, servers: dict[str, Any]
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE sessions SET mcp_servers_json = :v WHERE id = :id"
                ),
                {"v": _json_dumps(servers), "id": session_id},
            )

    async def get_effective_mcp_servers(
        self,
        session_id: str,
        connector_id: str,
    ) -> dict[str, Any]:
        from agent_server.core.runtime_config import merge_mcp_servers
        connector_mcp = await self.get_connector_mcp_servers(connector_id)
        session_mcp = await self.get_session_mcp_servers(session_id)
        return merge_mcp_servers(connector_mcp, session_mcp)
```

> 注意：`self._engine` 需与现有 Mixin 访问 engine 的方式一致——参考 `sessions.py` 中用法确认属性名。

---

## Step 5：Facade 层

**文件**：`server/agent_server/infra/repositories/runtime_config_facade.py`

在文件末尾追加 5 个 facade 方法（委托给 `self.mcp_servers`，若 Mixin 直接挂 Store 则 `self` 即可）：

实际上因 `McpServersRepositoryMixin` 是直接 mix 进 `Store` 的，方法直接在 `Store` 上可用，不需要额外 facade 文件，facade.py 只需把 Mixin 加进继承列表。

**文件**：`server/agent_server/infra/repositories/facade.py`

在 `Store` 基类列表加 `McpServersRepositoryMixin`：
```python
from agent_server.infra.repositories.mcp_servers import McpServersRepositoryMixin

class Store(
    ...
    McpServersRepositoryMixin,
    ...
):
```

---

## Step 6：Pydantic 模型

**文件**：`server/agent_server/core/models.py`

在文件末尾追加：
```python
class McpServersRequest(BaseModel):
    mcpServers: dict[str, Any]

class McpServersResponse(BaseModel):
    mcpServers: dict[str, Any]
```

---

## Step 7：API 端点

**文件**：`server/agent_server/api/connectors.py`

在文件内找 connector 相关端点集中处加入 4 个端点，使用现有的 `db: Store = Depends(get_db)` 和 `current_user` 依赖模式：

```python
@router.get("/api/connectors/{connector_id}/mcp-servers", response_model=McpServersResponse)
async def get_connector_mcp_servers(
    connector_id: str,
    db: Store = Depends(get_db),
    current_user: UserView = Depends(get_current_user),
) -> McpServersResponse:
    try:
        connector = await db.get_connector(connector_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="connector not found")
    if connector.userId != current_user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    servers = await db.get_connector_mcp_servers(connector_id)
    return McpServersResponse(mcpServers=servers or {})


@router.put("/api/connectors/{connector_id}/mcp-servers", response_model=McpServersResponse)
async def put_connector_mcp_servers(
    connector_id: str,
    body: McpServersRequest,
    db: Store = Depends(get_db),
    current_user: UserView = Depends(get_current_user),
) -> McpServersResponse:
    try:
        connector = await db.get_connector(connector_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="connector not found")
    if connector.userId != current_user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        sanitized = sanitize_mcp_servers(body.mcpServers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.set_connector_mcp_servers(connector_id, sanitized)
    return McpServersResponse(mcpServers=sanitized)
```

Session 端点同构，权限检查改为 `await db.get_session(session_id, user_id=current_user.id)` 模式（会抛 `KeyError` 若不属于该用户）。

---

## Step 8：turn.start 注入

**文件**：`server/agent_server/services/session_run.py`

在 `send_message` 中，`params` 组装完成后（约 L213 `if payload.attachments:` 块之后），`await self._store.start_active_run(...)` 之前：

```python
if session.runtime == "claude":
    try:
        effective_mcp = await self._store.get_effective_mcp_servers(
            session_id, session.connectorId
        )
        if effective_mcp:
            params["mcpServers"] = effective_mcp
    except Exception:
        logger.warning(
            "failed to load effective mcp servers for session {}; continuing without",
            session_id,
        )
```

---

## Step 9：测试

**文件**：`server/tests/test_backend_mvp.py`

参照现有的 `test_session_updated_context_usage_round_trips` 模式新增：

1. `test_connector_mcp_servers_round_trip` — PUT connector MCP → GET 回读一致
2. `test_session_mcp_servers_round_trip` — PUT session MCP → GET 回读一致
3. `test_effective_mcp_servers_merge` — connector + session 配置合并，session 同名覆盖
4. `test_mcp_servers_sanitize_rejects_sdk_type` — PUT sdk 类型 → 400
5. `test_mcp_servers_sanitize_rejects_bad_schema` — PUT 缺 command → 400
6. `test_turn_start_injects_mcp_servers` — mock `get_effective_mcp_servers` 返回非空配置，断言 RPC params 含 `mcpServers`
7. `test_turn_start_no_mcp_when_empty` — 有效 MCP 为空 dict 时 params 不含 `mcpServers`

---

## 验证命令

```bash
cd server
python -m pytest tests/ -q                    # 全套，预期 ~215+ passed
python -m pytest tests/ -q -k "mcp"          # 仅 MCP 新增测试
```

## Rollback

改动全为增量（加列、加函数、加端点、加注入段）：
- DB 列：无现有数据影响，列 nullable，旧代码读不到新列但不报错
- 端点：新增路由，不改现有路由
- 注入段：失败降级，不影响 turn 流程
- 若需回滚，删除新文件 `mcp_servers.py`，还原 `engine.py`/`facade.py`/`session_run.py`/`connectors.py` 的改动即可（DB 列保留无害）
