# 连接器开发规范（connector/）

> 本目录规范面向 `connector/` 下的 anywhere-cli 连接器。改动连接器代码前先读本文件，再按主题深入。

连接器（发布名 `anywhere-cli`）跑在真正拥有工作区和 Agent 运行时的那台机器上。它通过 HTTP/WebSocket 连到 server，在本地执行 RPC（文件、shell、终端、运行时轮次），并把归一化后的运行时/session 状态回传给后端。它是 server 的对侧：server 是控制面，连接器是执行面。运行时本身（Codex / Claude）由连接器在本地发现并驱动，凭据和文件权限都留在本地，不经过 server 代理。

## 技术栈

- Python 3.12+，全异步（`asyncio` + `async def`）。
- `websockets` 做与 server 的长连接；`httpx[socks]` 做鉴权和 ingest 上报。
- `claude-agent-sdk` 驱动 Claude；Codex 走 app-server 的 JSON-RPC stdio。
- Pydantic v2 定义 RPC 报文（`protocol.py`）。
- loguru 做日志，并可通过 `RpcLogSink` 把日志回传到 server。
- 依赖用 `uv` 管理，声明在 `connector/pyproject.toml`；控制台脚本 `anywhere-cli` / `agent-connector` 都指向 `connector.cli:main`。

## 规范索引

| 文档 | 说明 |
|------|------|
| [目录结构](./directory-structure.md) | 包分层、runtime/adapter/claude/codex/local 各自职责 |
| [运行时与 RPC](./runtime-and-rpc.md) | WebSocket 主循环、dispatch 路由、通知批处理、鉴权与重连 |
| [适配器](./adapters.md) | `Adapter` 协议、多运行时路由、notification_sink 约定 |
| [错误处理](./error-handling.md) | 异常 → RPC error code、鉴权失败不重试、fail-soft 边界 |
| [质量规范](./quality-guidelines.md) | 禁用模式、验证命令、测试约定 |

## 验证命令

改完连接器代码后，在 `connector/` 目录跑：

```bash
uv run ruff check connector tests
uv run pytest -q
```
