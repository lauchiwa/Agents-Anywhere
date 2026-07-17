# 实现计划：session.delete / session.fork RPC

## 参考实现

`rename_session` 是本任务完全对标的模板：
- `sdk_adapter.py` `rename_session()` 方法：L449–471
- `runtime.py` dispatch：`if method == "session.rename": return await self._resolve_adapter(params).rename_session(params)`
- `server/agent_server/api/sessions.py` rename 端点（搜 `rename` 找到）
- `web-next/src/features/dashboard/api.ts` 搜 `renameSession` 找到对应 web 方法

## Step 1：connector/connector/claude/sdk_adapter.py

在 `rename_session` 方法之后新增两个方法：

```python
async def delete_session(self, params: dict[str, Any]) -> dict[str, Any]:
    external_session_id = _optional_string(params.get("externalSessionId"))
    if not external_session_id:
        return {"ok": False, "reason": "externalSessionId required"}
    cwd = _optional_string(params.get("cwd"))
    sdk = self._load_sdk()
    delete_fn = getattr(sdk, "delete_session", None)
    if not callable(delete_fn):
        return {"ok": False, "reason": "sdk does not support delete_session"}
    try:
        if cwd:
            delete_fn(external_session_id, directory=cwd)
        else:
            delete_fn(external_session_id)
    except Exception:
        logger.debug(
            "sdk delete_session failed external_session_id={}",
            external_session_id,
            exc_info=True,
        )
        return {"ok": False, "reason": "delete_session failed"}
    return {"ok": True}

async def fork_session(self, params: dict[str, Any]) -> dict[str, Any]:
    external_session_id = _optional_string(params.get("externalSessionId"))
    if not external_session_id:
        return {"ok": False, "reason": "externalSessionId required"}
    cwd = _optional_string(params.get("cwd"))
    up_to_message_id = _optional_string(params.get("upToMessageId"))
    title = _optional_string(params.get("title"))
    sdk = self._load_sdk()
    fork_fn = getattr(sdk, "fork_session", None)
    if not callable(fork_fn):
        return {"ok": False, "reason": "sdk does not support fork_session"}
    try:
        kwargs: dict[str, Any] = {}
        if cwd:
            kwargs["directory"] = cwd
        if up_to_message_id:
            kwargs["up_to_message_id"] = up_to_message_id
        if title:
            kwargs["title"] = title
        result = fork_fn(external_session_id, **kwargs)
        return {"ok": True, "sessionId": result.session_id}
    except Exception:
        logger.debug(
            "sdk fork_session failed external_session_id={}",
            external_session_id,
            exc_info=True,
        )
        return {"ok": False, "reason": "fork_session failed"}
```

## Step 2：connector/connector/runtime.py

在 `if method == "session.rename":` 之后新增两行：

```python
if method == "session.delete":
    return await self._resolve_adapter(params).delete_session(params)
if method == "session.fork":
    return await self._resolve_adapter(params).fork_session(params)
```

## Step 3：server/agent_server/api/sessions.py

先读文件找到 rename 相关端点，然后参照模式新增。大致如下：

```python
class SessionDeleteRequest(BaseModel):
    externalSessionId: str
    cwd: str | None = None

class SessionForkRequest(BaseModel):
    externalSessionId: str
    cwd: str | None = None
    upToMessageId: str | None = None
    title: str | None = None

@router.post("/{session_id}/delete", response_model=RpcResponsePayload)
async def delete_session(session_id: str, body: SessionDeleteRequest, user_id=Depends(current_user_id), run_service=Depends(get_session_run_service)):
    return await run_service.delete_session_in_session(session_id, body, user_id=user_id)

@router.post("/{session_id}/fork", response_model=RpcResponsePayload)
async def fork_session(session_id: str, body: SessionForkRequest, user_id=Depends(current_user_id), run_service=Depends(get_session_run_service)):
    return await run_service.fork_session_in_session(session_id, body, user_id=user_id)
```

## Step 4：server/agent_server/services/session_run.py

先读文件找到 `rename_session_in_session` 方法作为参照，然后新增：

```python
async def delete_session_in_session(self, session_id, body, *, user_id) -> RpcResponsePayload:
    session = await self._store.get_session(session_id, user_id=user_id)
    params = {"sessionId": session_id, "runtime": session.runtime,
              "externalSessionId": body.externalSessionId, "cwd": body.cwd}
    result = await self._manager.request(session.connectorId, "session.delete", params)
    return RpcResponsePayload(ok=True, result=result)

async def fork_session_in_session(self, session_id, body, *, user_id) -> RpcResponsePayload:
    session = await self._store.get_session(session_id, user_id=user_id)
    params = {"sessionId": session_id, "runtime": session.runtime,
              "externalSessionId": body.externalSessionId, "cwd": body.cwd,
              "upToMessageId": body.upToMessageId, "title": body.title}
    result = await self._manager.request(session.connectorId, "session.fork", params)
    return RpcResponsePayload(ok=True, result=result)
```

## Step 5：web-next/src/features/dashboard/api.ts

先读文件找到 `renameSession` 方法，然后在之后新增：

```typescript
deleteSession(token: string, sessionId: string, externalSessionId: string, cwd?: string): Promise<RpcResponse<unknown>> {
  return this.client.post<RpcResponse<unknown>>(
    `/sessions/${encodeURIComponent(sessionId)}/delete`,
    { externalSessionId, cwd },
    { token },
  );
}

forkSession(token: string, sessionId: string, body: {
  externalSessionId: string;
  cwd?: string;
  upToMessageId?: string;
  title?: string;
}): Promise<RpcResponse<unknown>> {
  return this.client.post<RpcResponse<unknown>>(
    `/sessions/${encodeURIComponent(sessionId)}/fork`,
    body,
    { token },
  );
}
```

## Step 6：connector 单元测试

在 `test_claude_sdk_adapter.py` 新增两个测试，参照 `test_stop_task_rpc_calls_client_stop_task` 模式，但这里 SDK 方法是模块级函数（不是 client 方法），需要 mock `sdk.delete_session` 和 `sdk.fork_session`：

```python
async def test_delete_session_rpc():
    # mock sdk.delete_session 被调用，验证 ok: True
    ...

async def test_fork_session_rpc():
    # mock sdk.fork_session 返回 ForkSessionResult(session_id="new-uuid")
    # 验证返回 {ok: True, sessionId: "new-uuid"}
    ...
```

注意：`rename_session` 的测试是如何 mock SDK 模块级函数的——找到对应测试作为参考。

## 验证命令

```bash
cd connector && uv run pytest tests/test_claude_sdk_adapter.py -v -k "delete_session or fork_session" --tb=short
cd connector && uv run pytest --tb=short -q
cd server && uv run pytest --tb=short -q
cd web-next && npx tsc --noEmit
```
