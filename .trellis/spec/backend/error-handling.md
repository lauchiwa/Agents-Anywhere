# 错误处理

> 领域异常在 service 层抛出、在 API 边界翻译成 `HTTPException`。

## 分层原则

失败在 service 层用**领域异常**表达，只有到了 API 边界才翻成 HTTP。service 不认识 `HTTPException`，路由不猜 SQL 或 RPC 的错。

## Service 层：带 status_code 的领域异常家族

service 定义一个异常基类，子类挂各自的 `status_code`，这样边界层无脑映射即可：

```python
class SessionRunError(RuntimeError):
    status_code = 500
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

class SessionRunNotFoundError(SessionRunError):
    status_code = 404
class SessionRunConflictError(SessionRunError):
    status_code = 409
class SessionRunUpstreamError(SessionRunError):
    status_code = 502
```

service 内部把底层异常**转译**成领域异常，不要让底层异常泄漏到调用方：

```python
except ConnectorOfflineError as exc:
    raise SessionRunConflictError(str(exc)) from exc
except ConnectorRpcError as exc:
    raise SessionRunUpstreamError(exc.message or exc.code) from exc
```

参考文件：`agent_server/services/session_run.py`。

## API 边界：统一翻译

路由把领域异常翻成 `HTTPException`，用一个小 helper 收口，避免每个 handler 重复 `status_code` 映射：

```python
def _raise_session_run_error(exc: SessionRunError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
```

对没有领域异常包装的简单情况，直接在边界抛，并用 `from None` / `from exc` 保留因果链：

```python
raise HTTPException(status_code=404, detail="session not found") from None
raise HTTPException(status_code=422, detail=str(exc)) from exc
```

参考文件：`agent_server/api/sessions.py`。

## 状态码约定

| 场景 | 状态码 |
|------|--------|
| 资源不存在 | 404 |
| 入参非法 / 校验失败 | 422 |
| 状态冲突（connector 离线、session 只读、重复操作） | 409 |
| 上游 connector RPC 出错 | 502 |
| 未预期的内部错误 | 500 |

## 常见错误

- 在 service 层直接抛 `HTTPException`——HTTP 细节应留在边界。
- 让 `ConnectorRpcError`、`KeyError`、SQL 异常等底层异常穿透到路由，而不是转译成领域异常。
- `raise ... from exc` 的因果链丢失，日志里看不到根因。
- 在多个 handler 里重复手写同一套 status_code 映射，而不是收口到 helper。
