# Implement: Session rename

## 前置条件

Active task: `.trellis/tasks/07-15-connector-session-management`

## 步骤

### Step 1 — connector: ClaudeSdkAdapter.rename_session

文件：`connector/connector/claude/sdk_adapter.py`

在 `get_mcp_status` 方法之后（约 357 行后）新增：

```python
async def rename_session(self, params: dict[str, Any]) -> dict[str, Any]:
    external_session_id = _optional_string(params.get("externalSessionId"))
    title = _optional_string(params.get("title"))
    if not external_session_id or not title:
        return {"ok": False, "reason": "externalSessionId and title required"}
    cwd = _optional_string(params.get("cwd"))
    sdk = self._load_sdk()
    rename_fn = getattr(sdk, "rename_session", None)
    if not callable(rename_fn):
        return {"ok": False, "reason": "sdk does not support rename_session"}
    try:
        if cwd:
            rename_fn(external_session_id, title, directory=cwd)
        else:
            rename_fn(external_session_id, title)
    except Exception:
        logger.debug(
            "sdk rename_session failed external_session_id={} title={}",
            external_session_id,
            title,
            exc_info=True,
        )
        return {"ok": False, "reason": "rename_session failed"}
    return {"ok": True}
```

注意：SDK `rename_session` 是同步函数（参考 history_adapter 中 `list_sessions` 的调用方式），直接调用即可，不需要 run_in_executor。

### Step 2 — connector: dispatch 添加 session.rename 分支

文件：`connector/connector/runtime.py`

在 `dispatch` 方法中 `session.sync` 分支之后（约 341 行）添加：

```python
if method == "session.rename":
    adapter = self._resolve_adapter(params)
    handler = getattr(adapter, "rename_session", None)
    if not callable(handler):
        return {"ok": False, "reason": "runtime does not support rename"}
    return await handler(params)
```

### Step 3 — server: PATCH /sessions/{id} 同步 rename 到 connector

文件：`server/agent_server/api/sessions.py`

找到 `db.rename_session` 调用处（约 107 行），在 `db.rename_session` 调用之后、`publish_dashboard_changed` 之前添加 best-effort RPC：

```python
if payload.title is not None:
    try:
        session = await db.rename_session(session_id, payload.title, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Best-effort: sync new title to connector's SDK copy (custom_title on disk).
    # Skipped when connector is offline or session has no external ID.
    # DB is already updated so a failure here is non-fatal.
    if (
        session.externalSessionId
        and session.connectorId
        and manager.is_online(session.connectorId)
    ):
        try:
            await manager.request(
                session.connectorId,
                "session.rename",
                {
                    "sessionId": session_id,
                    "externalSessionId": session.externalSessionId,
                    "title": payload.title.strip(),
                    "cwd": session.cwd,
                    "runtime": session.runtime or "claude",
                },
                timeout=10,
            )
        except (ConnectorOfflineError, ConnectorRpcError):
            pass
```

注意：session 对象在 `db.rename_session` 后刷新，从 session 读 `externalSessionId`/`connectorId`/`cwd` 时用更新后的对象。

查看现有 session 对象有哪些字段（参考 `SessionView` 模型），确认 `session.cwd` 是否存在，若不存在则省略 cwd 字段。

### Step 4 — connector 测试

文件：`connector/tests/test_claude_sdk_adapter.py`

新增 4 个测试（放在 mcp_status 测试之后）：

```
test_claude_sdk_adapter_rename_session_calls_sdk
  - 构造 FakeSdk 带 rename_session = Mock
  - 调用 adapter.rename_session({"externalSessionId": "ext123", "title": "New Title", "cwd": "/repo"})
  - 断言 FakeSdk.rename_session 被调用且参数正确
  - 断言返回 {"ok": True}

test_claude_sdk_adapter_rename_session_without_cwd
  - 同上但不传 cwd
  - 断言 rename_session(external_id, title)（无 directory 参数）

test_claude_sdk_adapter_rename_session_missing_sdk_method
  - FakeSdk 没有 rename_session
  - 断言返回 {"ok": False, "reason": ...}

test_claude_sdk_adapter_rename_session_missing_params
  - 不传 externalSessionId 或 title
  - 断言返回 {"ok": False}
```

### Step 5 — dispatch 测试

文件：`connector/tests/test_connector_runtime.py`

新增：
```
test_connector_runtime_dispatches_session_rename_to_claude
  - FakeAdapter (with rename_session returning {"ok": True})
  - dispatch("session.rename", {"externalSessionId": "ext1", "title": "T", "runtime": "claude"})
  - 断言 handler 被调用，返回 {"ok": True}
```

### Step 6 — server 测试

文件：`server/tests/test_backend_mvp.py`

新增：
```
test_session_rename_syncs_to_connector_when_online
  - 创建 claude session（带 externalSessionId）
  - mock manager.request 和 manager.is_online → True
  - PATCH /sessions/{id} {"title": "New Name"}
  - 断言 manager.request 调用了 "session.rename" 且 params 正确

test_session_rename_skips_connector_when_offline
  - 同上但 manager.is_online → False
  - 断言 manager.request 未被调用，响应仍 200
```

参考 `test_session_updated_permission_mode_persists_to_override` 的模式（已有 manager mock 示例）。

### Step 7 — 验证命令

```bash
cd connector && source .venv/bin/activate && python -m pytest tests/test_claude_sdk_adapter.py tests/test_connector_runtime.py -x -q 2>&1 | tail -10
cd server && source .venv/bin/activate && python -m pytest tests/test_backend_mvp.py -k "rename" -x -q 2>&1 | tail -10
```

## 关键约束

- server 的 rename RPC 调用是 best-effort：DB 更新必须先于 RPC，RPC 失败不影响 HTTP 响应
- connector dispatch 用 `_resolve_adapter(params)` 不要硬编码 claude
- SDK `rename_session` 是同步方法，直接调用（不用 executor）
- 不改动 history_adapter（rename 只更新磁盘文件 metadata，不影响同步逻辑）
