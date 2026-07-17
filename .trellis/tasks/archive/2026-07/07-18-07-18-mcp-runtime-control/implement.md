# 实现计划：MCP 运行时控制 + context.usage 主动查询 RPC

## 参考实现（完全对照）

`stop_task` 是本任务所有三个功能的实现模板：
- `sdk_adapter.py` `stop_task()` 方法：L273–294
- `runtime.py` dispatch：`if method == "task.stop": return await self._resolve_adapter(params).stop_task(params)`
- `server/agent_server/services/session_run.py` `stop_task_in_session()`
- `server/agent_server/api/sessions.py` `StopTaskRequest` + `@router.post("/{session_id}/task/stop")`
- `web-next/src/features/dashboard/api.ts` `stopTask()`

## Step 1：connector/connector/claude/sdk_adapter.py

在 `stop_task` 方法之后新增三个方法：

```python
async def reconnect_mcp_server(self, params: dict[str, Any]) -> dict[str, Any]:
    session_id = _required(params, "sessionId")
    server_name = _required(params, "serverName")
    runtime = self._sessions.get(session_id)
    if runtime is None:
        return {"ok": False, "reason": "session not registered"}
    client = runtime.client
    if client is None:
        return {"ok": False, "reason": "no active Claude SDK client"}
    try:
        await client.reconnect_mcp_server(server_name)
    except Exception as exc:
        logger.debug("reconnect_mcp_server failed session_id={} server_name={}", session_id, server_name, exc_info=True)
        return {"ok": False, "reason": str(exc) or "reconnect_mcp_server failed"}
    return {"ok": True}

async def toggle_mcp_server(self, params: dict[str, Any]) -> dict[str, Any]:
    session_id = _required(params, "sessionId")
    server_name = _required(params, "serverName")
    enabled = bool(params.get("enabled", True))
    runtime = self._sessions.get(session_id)
    if runtime is None:
        return {"ok": False, "reason": "session not registered"}
    client = runtime.client
    if client is None:
        return {"ok": False, "reason": "no active Claude SDK client"}
    try:
        await client.toggle_mcp_server(server_name, enabled)
    except Exception as exc:
        logger.debug("toggle_mcp_server failed session_id={} server_name={} enabled={}", session_id, server_name, enabled, exc_info=True)
        return {"ok": False, "reason": str(exc) or "toggle_mcp_server failed"}
    return {"ok": True}

async def get_context_usage(self, params: dict[str, Any]) -> dict[str, Any]:
    session_id = _required(params, "sessionId")
    runtime = self._sessions.get(session_id)
    if runtime is None:
        return {"ok": False, "reason": "session not registered"}
    client = runtime.client
    if client is None:
        return {"ok": False, "reason": "no active Claude SDK client"}
    getter = getattr(client, "get_context_usage", None)
    if not callable(getter):
        return {"ok": False, "reason": "get_context_usage not available"}
    try:
        raw = await getter()
        usage = _context_usage_from_response(raw)
        return {"ok": True, "usage": usage}
    except Exception as exc:
        logger.debug("get_context_usage failed session_id={}", session_id, exc_info=True)
        return {"ok": False, "reason": str(exc) or "get_context_usage failed"}
```

注意：`_context_usage_from_response` 已在 `sdk_adapter.py` 中存在（私有函数，供 `_capture_context_usage` 使用）。直接复用。
需要先 Read 文件确认该函数名和签名，然后在正确位置插入三个方法。

## Step 2：connector/connector/runtime.py

在 `if method == "task.stop":` 之后新增三行 dispatch：

```python
if method == "mcp.reconnect":
    return await self._resolve_adapter(params).reconnect_mcp_server(params)
if method == "mcp.toggleServer":
    return await self._resolve_adapter(params).toggle_mcp_server(params)
if method == "context.usage":
    return await self._resolve_adapter(params).get_context_usage(params)
```

## Step 3：server/agent_server/services/session_run.py

参照 `stop_task_in_session`，新增三个 service 方法：

```python
async def reconnect_mcp_server_in_session(self, session_id, server_name, *, user_id) -> RpcResponsePayload:
    session = await self._store.get_session(session_id, user_id=user_id)
    params = {"sessionId": session_id, "runtime": session.runtime, "serverName": server_name}
    result = await self._manager.request(session.connectorId, "mcp.reconnect", params)
    return RpcResponsePayload(ok=True, result=result)

async def toggle_mcp_server_in_session(self, session_id, server_name, enabled, *, user_id) -> RpcResponsePayload:
    session = await self._store.get_session(session_id, user_id=user_id)
    params = {"sessionId": session_id, "runtime": session.runtime, "serverName": server_name, "enabled": enabled}
    result = await self._manager.request(session.connectorId, "mcp.toggleServer", params)
    return RpcResponsePayload(ok=True, result=result)

async def get_context_usage_in_session(self, session_id, *, user_id) -> RpcResponsePayload:
    session = await self._store.get_session(session_id, user_id=user_id)
    params = {"sessionId": session_id, "runtime": session.runtime}
    result = await self._manager.request(session.connectorId, "context.usage", params)
    return RpcResponsePayload(ok=True, result=result)
```

## Step 4：server/agent_server/api/sessions.py

参照 `StopTaskRequest` 和 `stop_task` endpoint，新增：

```python
class McpReconnectRequest(BaseModel):
    serverName: str

class McpToggleServerRequest(BaseModel):
    serverName: str
    enabled: bool

@router.post("/{session_id}/mcp/reconnect", response_model=RpcResponsePayload)
async def reconnect_mcp_server(session_id: str, body: McpReconnectRequest, user_id=Depends(current_user_id), run_service=Depends(get_session_run_service)):
    return await run_service.reconnect_mcp_server_in_session(session_id, body.serverName, user_id=user_id)

@router.post("/{session_id}/mcp/toggle", response_model=RpcResponsePayload)
async def toggle_mcp_server(session_id: str, body: McpToggleServerRequest, user_id=Depends(current_user_id), run_service=Depends(get_session_run_service)):
    return await run_service.toggle_mcp_server_in_session(session_id, body.serverName, body.enabled, user_id=user_id)

@router.get("/{session_id}/context/usage", response_model=RpcResponsePayload)
async def get_context_usage(session_id: str, user_id=Depends(current_user_id), run_service=Depends(get_session_run_service)):
    return await run_service.get_context_usage_in_session(session_id, user_id=user_id)
```

## Step 5：web-next/src/features/dashboard/api.ts

参照 `stopTask()`，新增三个方法（在 `stopTask` 之后）：

```typescript
mcpReconnect(token: string, sessionId: string, serverName: string): Promise<RpcResponse<unknown>> {
  return this.client.post<RpcResponse<unknown>>(
    `/sessions/${encodeURIComponent(sessionId)}/mcp/reconnect`,
    { serverName },
    { token },
  );
}

mcpToggleServer(token: string, sessionId: string, serverName: string, enabled: boolean): Promise<RpcResponse<unknown>> {
  return this.client.post<RpcResponse<unknown>>(
    `/sessions/${encodeURIComponent(sessionId)}/mcp/toggle`,
    { serverName, enabled },
    { token },
  );
}

getContextUsage(token: string, sessionId: string): Promise<RpcResponse<unknown>> {
  return this.client.get<RpcResponse<unknown>>(
    `/sessions/${encodeURIComponent(sessionId)}/context/usage`,
    { token },
  );
}
```

## Step 6：connector 单元测试

在 `connector/tests/test_claude_sdk_adapter.py` 新增三个测试，参照 `test_stop_task_rpc_calls_client_stop_task` 的模式：

1. `test_mcp_reconnect_rpc_calls_client_method` — mock client，验证 `reconnect_mcp_server(server_name)` 被调用，返回 `ok: True`
2. `test_mcp_toggle_server_rpc_calls_client_method` — mock client，验证 `toggle_mcp_server(server_name, enabled)` 被调用
3. `test_context_usage_rpc_returns_usage` — mock client `get_context_usage()` 返回 fake 数据，验证 `ok: True` 且有 `usage` 字段

## 验证命令

```bash
cd connector && uv run pytest tests/test_claude_sdk_adapter.py -v -k "mcp or context_usage"
cd connector && uv run pytest --tb=short -q
cd server && uv run pytest --tb=short -q
cd web-next && npx tsc --noEmit
```
