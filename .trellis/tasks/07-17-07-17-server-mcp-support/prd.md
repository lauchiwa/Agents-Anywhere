# 服务端 MCP 支持：DB列+API+turn.start注入

## Background

能力差集分析（2026-07-15）将"服务端 MCP 支持"标记为已实现，但 2026-07-17 全项目审查确认该标记有误：服务端代码中完全不存在 MCP 相关逻辑（无 DB 列、无 API、无注入）。Connector 侧已完成外部 MCP server 配置注入（本地 `mcp.json` 加载）和 `mcp.status` RPC，但服务端对此毫无感知，用户无法通过 Web/Android 管理 MCP 配置，`turn.start` 也不携带 MCP 上下文。

## Goal

在服务端实现 MCP 服务器配置的存储、读取与注入，使用户可通过 Web 界面管理 Connector 级和 Session 级的 MCP 服务器配置，并在每次 turn.start 时将有效配置注入给 Connector。

## Scope

- **Connector 级 MCP 配置**：与 Connector 绑定，作为该 Connector 所有 Session 的默认配置
- **Session 级 MCP 配置**：覆盖 Connector 级同名 server（merge 语义：session 配置中出现的 server 名优先）
- **turn.start 注入**：`send_message` 时将合并后的有效 MCP 配置通过 RPC params 注入给 Connector（`mcpServers` 字段）
- **不在范围**：Android MCP 编辑器 UI（Compose 动态列表成本高，后续任务）；内进程 MCP（`@tool` SDK 类型）

## Requirements

### 存储
- `connectors` 表新增 `mcp_servers_json` TEXT 列（nullable，空=无配置）
- `sessions` 表新增 `mcp_servers_json` TEXT 列（nullable，空=无配置）
- 使用 `_ensure_compat_schema` 非破坏性 ALTER 迁移（async + sync 两路径都加）

### 清洗校验（`sanitize_mcp_servers`）
- 入参必须是 `dict[str, dict]`，否则 400
- 每个 server 的 `type` 必须是 `stdio` / `http` / `sse`，`sdk` 类型拒绝（400）
- `stdio` 必须有非空字符串 `command`；`http`/`sse` 必须有非空字符串 `url`
- 未知 key 拒绝（400，严格校验防止配置漂移）
- `env`/`headers` 明文存储并完整回显（配置需可见；日志中不打印 mcpServers 值）

### API 端点（4 个）
- `GET /api/connectors/{connector_id}/mcp-servers` — 读取 Connector 级配置
- `PUT /api/connectors/{connector_id}/mcp-servers` — 写入 Connector 级配置（替换，非 patch）
- `GET /api/sessions/{session_id}/mcp-servers` — 读取 Session 级配置
- `PUT /api/sessions/{session_id}/mcp-servers` — 写入 Session 级配置

### 合并与注入（`get_effective_mcp_servers`）
- 合并规则：`{**connector_mcp, **session_mcp}`（session 中同名 server 完整替换 connector 同名配置，非字段级 merge）
- `send_message` 中：若合并结果非空则在 RPC params 中注入 `mcpServers`；结果为空则省略
- 读取/合并失败时降级为空（不阻断 turn，记录 warning 日志）

### 权限
- Connector MCP API：调用方必须是该 Connector 的 owner（user_id 校验）
- Session MCP API：调用方必须是该 Session 的 owner

## Acceptance Criteria

- [ ] `connectors` 和 `sessions` 表各有 `mcp_servers_json` 列（旧数据库无需手动迁移，启动自动 ALTER）
- [ ] 4 个 API 端点正常读写，写入时 `sanitize_mcp_servers` 清洗拒绝非法配置（400）
- [ ] `sdk` 类型 server 被 PUT 接口 400 拒绝
- [ ] `send_message` 调用后，RPC `turn.start` 的 params 中含正确合并的 `mcpServers`（当有效配置非空时）
- [ ] Connector 级 + Session 级 round-trip 测试通过
- [ ] 合并语义测试：Session 同名 server 覆盖 Connector 配置
- [ ] 降级测试：DB 读取异常时 turn.start 正常继续（无 mcpServers 字段）
- [ ] 现有服务端测试（208 passed）无回归

## Notes

- `mcpServers` 不走 runtime_settings 体系：runtime_settings 有固定字段 schema，无法承载自由命名的 dict-of-dict；走独立 JSON blob 列 + 专门 API
- 实现参照 `contextUsage`/`rateLimit` 的 DB 列 + 服务端 JSON blob 模式，但读写由专用 API 端点驱动（而非 connector push）
- Web 编辑器 UI 和会话级 UI 入口参照 web-next 中的 `mcp-servers-editor.tsx`（若已存在）；若不存在则 API 先行，UI 为后续任务
