# 质量规范

> 连接器代码的禁用/必用模式、测试与验证约定。

## 必用模式

- **全异步**：所有 I/O 走 `async def` + `await`。跨运行时接口用 `Awaitable` 类型标注（见 `adapter.py`）。
- **HTTP client 走 `_new_http_client`**：它统一处理 loopback 代理豁免和 `trust_env`。不要散落 `httpx.AsyncClient(...)`。
- **通知走 `notification_sink` / `send_backend_notification`**：适配器不直接碰传输层。
- **模块级常量抬到文件顶部**：超时、刷新窗口、批大小等都是命名常量（`FLUSH_WINDOW_SECONDS`、`RUNTIME_SYNC_TIMEOUT_SECONDS`、`ACCESS_TOKEN_REFRESH_SKEW_SECONDS`），不要写魔法数字。

## 禁用模式

- 在适配器里 import `connector.runtime` 或直接访问 WebSocket / httpx——运行时逻辑必须和传输层解耦。
- 让 `runtime.py` 直接依赖 `local/` 下的具体后端类——统一走 `LocalOps` 门面。
- 对着已吊销的凭据重连——`ConnectorAuthenticationError` 必须停机。
- 在后台维护循环里让异常逸出——必须 fail-soft。
- 逐条同步 POST 流式通知——必须走批处理队列。

## 测试约定

- 测试用鸭子类型的 fake 适配器（`FakeAdapter`）验证 dispatch 路由和通知流，不依赖真实运行时。`Adapter` 是 `runtime_checkable` Protocol，fake 无需继承。
- 运行时归一化/reducer 有 parity 测试（`test_claude_timeline_parity.py`）保证归一化输出稳定，改归一化逻辑时先看它。
- 每个子系统一个测试文件，命名 `test_<subsystem>.py`（`test_connector_runtime.py`、`test_terminal_backend.py`、`test_claude_sdk_adapter.py` 等）。

参考文件：`connector/tests/test_connector_runtime.py`、`connector/tests/test_claude_timeline_parity.py`。

## 验证命令

在 `connector/` 目录跑：

```bash
uv run ruff check connector tests
uv run pytest -q
```
