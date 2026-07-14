# 适配器（Adapter）

> 每个运行时（Codex / Claude / 未来的 OpenCode、ACP）如何接入连接器。改动运行时集成前先读本文件。

## `Adapter` 协议是运行时接入的唯一契约

`adapter.py` 定义了 `Adapter`（`typing.Protocol`, `runtime_checkable`）。`BackendRpcClient` 持有一个 `dict[str, Adapter]`（`self.adapters`），按 `params["runtime"]` 路由。每个适配器必须实现：

- `create_session` / `sync_session` / `sync_existing_sessions`
- `start_turn` / `interrupt_turn` / `resolve_approval`
- 一个可写的 `notification_sink` 属性（构造后由 client 注入）

新增运行时：新建子包实现这些方法，在 `BackendRpcClient.__init__` 的 `self.adapters` 里注册。因为是 `Protocol` 而非基类，适配器不需要继承任何东西，鸭子类型即可，测试里的 `FakeAdapter` 就是这么做的。

参考文件：`connector/adapter.py`、`connector/tests/test_connector_runtime.py` 的 `FakeAdapter`。

## notification_sink 是适配器向上回传的唯一通道

适配器不直接碰 WebSocket，也不直接 POST。它通过 `notification_sink(method, params)` 把归一化后的通知交给 client，由 client 决定批处理还是同步发。

- client 在 `__init__` 里给每个适配器注入 `notification_sink = self.send_backend_notification`（若适配器没自带）。
- 存量同步这类会一次产出大批通知的方法，额外接受一个 `notification_sink` 参数（`Callable[[list], Awaitable]`），client 传入 `enqueue_backend_notifications`。

不要在适配器里 import `runtime` 或直接访问 `self._ws` / `httpx`——那会把运行时逻辑和传输层耦死。

参考文件：`connector/runtime.py` 的 `BackendRpcClient.__init__`（注入 sink）、`enqueue_backend_notifications`。

## 存量同步用 NotImplementedError 显式弃权

不是每个适配器都支持存量 session 同步。`_sync_existing_loop` 和 `_force_resync_runtime` 都把 `NotImplementedError` 当作「该适配器不支持，跳过」来处理，而不是错误。桩适配器（stub）就靠抛 `NotImplementedError` 优雅退出。

新增一个还没实现历史同步的运行时时，让 `sync_existing_sessions` 抛 `NotImplementedError`，不要返回空结果假装成功。

参考文件：`connector/runtime.py` 的 `_sync_existing_loop`、`_force_resync_runtime`。

## 运行时发现与 rewire

capability 发现（`capabilities.py`）和适配器是分离的：发现只负责扫描本地有没有可用的 Codex/Claude 并产出 report，`_rewire_codex` / `_rewire_claude` 再把发现到的 `LaunchTarget` 装到对应适配器上。

- 扫描（`capabilities.scanRuntime`）只做发现和 rewire，**不推送 session**。session 同步是后端在提交用户意图后单独发的 `capabilities.forceResyncRuntime`。顺序颠倒会导致 session 在运行时仍处于「用户已禁用」状态时到达 ingest 而被过滤掉（`_scan_runtime` 的注释详述了这个坑）。

参考文件：`connector/runtime.py` 的 `_scan_runtime`、`_rewire_codex`、`_rewire_claude`；`connector/capabilities.py`。
