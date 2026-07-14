# 错误处理

> 连接器的异常约定：什么该重试、什么该弃权、异常怎么变成 RPC error。

## RPC 异常统一在 `handle_message` 边界翻译

`dispatch` 里的处理逻辑可以自由抛异常，不需要自己拼 error 响应。`handle_message` 在最外层 `try/except` 捕获所有异常并：

1. `logger.exception(...)` 记录带 method/id 的堆栈。
2. 取 `code = getattr(exc, "code", None) or exc.__class__.__name__` 作为 error code。
3. 用 `send_response(ok=False, error={"code": code, "message": str(exc)})` 回给后端。

这意味着：想让后端识别某类错误（比如把 `StaleFileError` 翻成 HTTP 412），就在异常类上加一个 `code` 属性，后端按 code 分流。参数校验类错误直接 `raise ValueError(...)`，会被翻成 code=`ValueError`。

参考文件：`connector/runtime.py` 的 `handle_message`。

## 鉴权错误不可重试，其余可重试

见 runtime-and-rpc.md 的详述，核心规则：`ConnectorAuthenticationError` 一律向上抛、停止进程，绝不进重连分支。HTTP 401 先 `force=True` 刷新 token 重试一次，仍失败才升级为 `ConnectorAuthenticationError`。

参考文件：`connector/runtime.py` 的 `run_forever`、`authenticate`、`_get_json`、`_post_batch`。

## 后台循环 fail-soft，不要让一个错误拖垮连接

存量同步、偏好推送、capability 发现这些后台工作，出错时记日志继续，不能抛出去中断主循环：

- `_sync_existing_loop`：`TimeoutError` 记 warning，其他异常 `logger.exception` 后继续下一个运行时。
- `_flush_loop`：POST 失败 `logger.exception` 后继续（丢一条通知也好过挂住连接）。
- `_discover_and_publish_capabilities` / `_push_preferences_if_changed`：整段 `try/except` 包住，出错记日志后 return。

判断标准：**主 RPC 路径**的错误要如实回传给后端（走 `handle_message` 翻译）；**后台维护循环**的错误 fail-soft、记日志、继续。

参考文件：`connector/runtime.py` 的 `_sync_existing_loop`、`_flush_loop`、`_push_preferences_if_changed`。

## 常见错误

- 在 `dispatch` 分支里自己 `try/except` 拼 error 响应——多余，交给 `handle_message` 统一处理。
- 后台循环里让异常逸出——会中断 `run_once` 触发无谓重连。
- 把 `NotImplementedError`（适配器弃权信号）当成真错误记 error——它是正常的「不支持」信号。
