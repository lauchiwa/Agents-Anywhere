# 质量规范

> 异步一致性、类型模型、单例依赖，以及提交前的验证命令。

## 必须遵守

- **全链路异步。** 数据库、RPC、文件都是 `async`。路由和 service 用 `async def`，DB 走 `AsyncEngine`/`AsyncConnection`。不要在异步路径里塞同步阻塞调用。
- **API 数据用 Pydantic v2 模型。** 请求/响应类型定义在 `core/models.py`，不要在路由里传裸 `dict`。
- **单例只从 `app.state` 拿，依赖只从 `deps.py` 拿。** `Store`、RPC manager、broker 都是启动时装配的单例，路由通过 `Depends(get_xxx)` 获取，不要自己 new。参考 `agent_server/deps.py`。
- **UTC 时间统一走 `core/utc.py` 的 `utc_now()`**，产出 ISO8601 带 `Z` 的字符串，不要各处自己拼 `datetime.now()`。

## 禁用模式

- 在 service 层抛 `HTTPException`（HTTP 细节留在 API 边界，见错误处理规范）。
- 在路由或 service 里直接 `Store(...)` 或自建 engine——破坏单例、绕过 schema 初始化。
- 裸 `except Exception: pass` 吞异常。确需宽捕获（如清理路径）时加 `# noqa: BLE001` 并写明原因，参考 timeline 锁的 unlock 兜底。
- 用 f-string 拼日志消息（见日志规范）。

## 类型与序列化

- JSON 序列化用统一 helper：`json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`，保证跨行稳定、便于比对 `contentHash`。参考 `infra/timeline_store.py` 的 `_json_dumps`。
- 落库前后用 `TimelineItem.model_validate_json` / `model_dump(exclude_none=True)` 走 Pydantic，不要手搓 dict。

## 测试要求

- 新增端点或 service 行为要有对应测试，放 `server/tests/`。
- 测试直接构造 `Store`（不经 FastAPI lifespan），所以 `Store.__init__` 会同步建表和 seed——新增依赖 lifespan 的初始化时要保证测试路径也能拿到。

## 验证命令

提交前在 `server/` 目录跑：

```bash
uv run ruff check . --exclude .venv
uv run pytest -q
```
