# PRD: MCP Server 配置编辑器（Web + Android）

## 背景

后端 MCP server 配置 API（GET/PUT `/api/connectors/{id}/mcp-servers` 和 `/api/sessions/{id}/mcp-servers`）已于 `c745706` 完整实现，包含两级合并语义（session 覆盖 connector 同名条目）。连接器注入也已就绪。Web 和 Android 客户端均无配置 UI，用户无法从 app 管理 MCP servers。

## 目标

在 Web 和 Android 端实现 MCP server 配置编辑 UI，让用户可以：
- 查看、新增、编辑、删除 connector 级别的 MCP server
- 查看、新增、编辑、删除 session 级别的 MCP server（覆盖 connector 级别）

## 数据结构

Wire format：`{ "mcpServers": { "<name>": config } }`

**stdio 类型**
```
{ type: "stdio", command: string, args?: string[], env?: Record<string, string> }
```

**http / sse 类型**
```
{ type: "http" | "sse", url: string, headers?: Record<string, string> }
```

## 范围

### Web

1. `web-next/src/features/dashboard/types.ts` — 添加 `McpServerConfig` TypeScript 类型
2. `web-next/src/lib/api.ts` — 添加 4 个 API 方法（connector + session 两级 get/put）
3. `web-next/src/components/mcp-servers-editor.tsx` — 新建可复用编辑器组件
4. 设备详情页 — 添加 connector MCP section（复用编辑器组件）
5. Session 详情侧边栏 — 添加 session MCP section（复用编辑器组件）
6. `messages/en.json` + `messages/zh-CN.json` — i18n 键

### Android

1. `api/McpServersDtos.kt`（新文件）— 数据类 + JSON 序列化辅助
2. `api/DevicesApi.kt` — 添加 `getConnectorMcpServers` / `putConnectorMcpServers`
3. `api/SessionsApi.kt` — 添加 `getSessionMcpServers` / `putSessionMcpServers`
4. `feature/devices/DevicesController.kt` — 添加 MCP controller 方法
5. `feature/sessions/SessionsController.kt` — 添加 MCP controller 方法
6. `ui/screens/devices/ConnectorMcpServersSheet.kt`（新文件）— connector 级编辑器
7. `ui/screens/sessiondetail/SessionMcpServersSheet.kt`（新文件）— session 级编辑器
8. `DeviceDetailScreen.kt` — 添加"MCP Servers"入口
9. `AgentsAnywhereApp.kt` 或 `SessionDetailScreen.kt` — 添加 session MCP 入口
10. `strings.xml` + `values-zh-rCN/strings.xml` — 字符串资源

## 不在范围内

- 内进程 SDK MCP server（`@tool`/`create_sdk_mcp_server`）
- MCP server 连通性测试
- 复杂权限/凭证加密（沿用现有明文策略）
- Android MCP status / reconnect 面板

## 验收标准

1. Web 设备详情页可增删改 connector MCP server，PUT 后刷新仍持久
2. Web session 详情页可增删改 session MCP server
3. Android 设备详情屏可打开 MCP Servers Sheet，完成增删改保存
4. Android 会话详情屏可打开 MCP Servers Sheet，完成增删改保存
5. 类型校验：stdio 必填 command，http/sse 必填 url；空 name 禁止保存
6. `tsc` 无错，`compileDebugKotlin` 无错，现有测试无回归
7. 所有文案有 en + zh-CN 两套
