# 日志规范

> 统一用 loguru，惰性占位（`{}`）传参，日志里带上定位用的关键 id。

## 用 loguru，不要 f-string 拼消息

全后端用 `from loguru import logger`。消息用 loguru 的 `{}` 占位，参数按位置传入，不要提前用 f-string 拼好：

```python
logger.info("connector connected: {}", connector_id)
logger.warning("preferences update for unknown connector connector_id={}", connector_id)
```

这样参数在真正需要输出时才格式化，级别被过滤时省去开销，参考 `agent_server/api/connector_ingress.py`。

## 日志级别

| 级别 | 用途 | 例子 |
|------|------|------|
| `info` | 正常生命周期事件 | connector 连接/断开、启动时静态目录路径 |
| `warning` | 可恢复的异常状况、慢操作诊断 | 未知 connector 的更新、timeline 锁超阈值 |
| `error` | 明确失败但已处理 | advisory lock 获取失败 |
| `exception` | 捕获异常并需要堆栈 | RPC 处理里的意外异常 |

`logger.exception(...)` 只在 `except` 块里用，它会自动带上堆栈。参考 `agent_server/api/connectors.py`、`agent_server/services/runtime_activation.py`。

## 日志要能定位

每条日志带上排障用的关键标识——`connector_id`、`session_id`、耗时等。timeline 锁诊断是范例：把等待拆成 checkout / acquire / hold 三段，各自带 `session_id` 和 `seconds`，超阈值才 warning，稳态运行时保持安静：

```python
logger.warning(
    "timeline advisory lock held long session_id={} seconds={:.2f}",
    session_id,
    hold_seconds,
)
```

参考文件：`agent_server/infra/repositories/timeline.py`。

## 不该记的

- 密码、token、connector secret、auth header 等敏感值。tokens 只记哈希或 id，不记明文（参考 store 里 token 一律 `sha256` 后落库）。
- 完整的文件内容、大 payload。需要时记长度或摘要。

## 常见错误

- 用 `logger.info(f"...{x}...")` 而不是 `logger.info("...{}", x)`。
- warning/error 不带任何 id，出问题时无法定位是哪个 session/connector。
- 稳态路径打太多 info，把真正的诊断信息淹没。
