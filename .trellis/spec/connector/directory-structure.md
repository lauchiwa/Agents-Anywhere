# 目录结构与分层

> `connector/connector/` 的包职责划分与归位规则。

## 顶层模块职责

| 模块/包 | 放什么 |
|---------|--------|
| `runtime.py` | `BackendRpcClient` + `ConnectorConfig`：WebSocket 主循环、RPC dispatch、鉴权、通知批处理。连接器的中枢 |
| `adapter.py` | `Adapter` 协议：每个运行时后端客户端的统一接口 |
| `protocol.py` | Pydantic RPC 报文模型（`RpcRequest` / `RpcResponse` / `RpcNotification`） |
| `capabilities.py` | 本地运行时发现（扫描 Codex / Claude 是否可用），产出 capability report |
| `launch.py` | `LaunchTarget`：把「CLI 路径 / App 路径」抽象成可执行命令 |
| `claude/` | Claude 相关：SDK 适配、历史适配、事件归一化、timeline reducer、信任与偏好 |
| `codex/` | Codex 相关：app-server JSON-RPC 客户端、适配、历史、reducer |
| `local/` | 本地操作后端：文件、shell、终端。按平台分 Unix/Windows 实现 |
| `local_ops.py` | `LocalOps` 门面：把 `local/` 各后端统一成一组 RPC 方法 |
| `logging.py` | loguru logger + `RpcLogSink`（把日志作为通知回传 server） |
| `sync_state.py` | `SqliteSyncStateStore`：持久化各运行时的 session 同步游标 |
| `cli.py` | `anywhere-cli` 命令行入口（configure / start） |

判断放哪：和 server 通信、路由 RPC → `runtime.py`；驱动某个具体运行时 → `claude/` 或 `codex/`；在本地机器上读写文件/跑命令/开终端 → `local/`（对外统一走 `LocalOps`）；跨运行时共享的接口约定 → `adapter.py` / `protocol.py`。

## 运行时子包对称结构

`claude/` 和 `codex/` 各自内部保持相似的角色划分，便于对照：

- **adapter**（`claude/sdk_adapter.py`、`codex/adapter.py`）：实现 `Adapter` 协议，是运行时对 `BackendRpcClient` 的入口。
- **归一化 + reducer**（`claude/normalizers.py` + `claude/timeline_reducer.py`、`codex/reducer.py`）：把运行时原生事件转成后端 timeline item。
- **history**（`claude/history_adapter.py`、`codex/history.py`）：读取运行时本地历史，做存量 session 同步。

新增一个运行时（如 OpenCode / ACP）时，照这个结构建子包，实现 `Adapter` 协议，然后在 `BackendRpcClient.adapters` 里注册。

参考文件：`connector/adapter.py`、`connector/claude/sdk_adapter.py`、`connector/codex/adapter.py`。

## 本地操作统一走 `LocalOps` 门面

`local/` 下按能力和平台拆分后端（`file_ops.py`、`shell.py`、`terminal.py`，shell 有 `UnixShellBackend` / `WindowsShellBackend`），但对外只暴露 `LocalOps` 一个门面。`BackendRpcClient.dispatch` 里所有 `fs.*` / `shell.*` / `terminal.*` 方法都转发到 `self.local_ops` 的对应方法，不直接碰具体后端。

新增本地能力时：在对应后端实现，再在 `LocalOps` 上加一个转发方法，最后在 `dispatch` 里挂路由。不要让 `runtime.py` 直接 import `local/` 的具体后端类。

参考文件：`connector/local_ops.py`、`connector/local/ops.py`。

## 命名约定

- 运行时子包按运行时名命名（`claude/` / `codex/`），内部文件按角色命名（`adapter` / `reducer` / `history` / `normalizers`）。
- 模块级私有 helper 用前导下划线（`_ws_url`、`_is_loopback_url`、`_coalesce_timeline_item_upserts`）。
- RPC 方法名用点分命名空间（`session.create`、`fs.readDir`、`terminal.relay.connect`），与 `dispatch` 分支一一对应。
