# Design: MCP Server 配置编辑器

## 架构

两端均采用"加载→本地编辑草稿→保存"模式，不做乐观更新，避免与服务端验证失步。

## Web 端设计

### 类型（types.ts）

```typescript
export type McpServerType = "stdio" | "http" | "sse"

export interface McpServerConfig {
  type: McpServerType
  // stdio only
  command?: string
  args?: string[]
  env?: Record<string, string>
  // http/sse only
  url?: string
  headers?: Record<string, string>
}

export type McpServersMap = Record<string, McpServerConfig>
```

### API（api.ts）

4 个方法，统一返回 `McpServersMap`：
```typescript
getConnectorMcpServers(connectorId: string): Promise<McpServersMap>
putConnectorMcpServers(connectorId: string, servers: McpServersMap): Promise<McpServersMap>
getSessionMcpServers(sessionId: string): Promise<McpServersMap>
putSessionMcpServers(sessionId: string, servers: McpServersMap): Promise<McpServersMap>
```

### 编辑器组件（mcp-servers-editor.tsx）

```typescript
McpServersEditor({
  scope: "connector" | "session"
  scopeId: string          // connectorId 或 sessionId
  readOnly?: boolean
})
```

- `useQuery` 加载，`useMutation` 保存
- 本地 state：`draft: McpServerDraft[]`（数组化方便增删，保存时重新序列化成 map）
- `McpServerDraft = { key: string, name: string, config: McpServerConfig, _id: string /* 临时 uuid */ }`
- 类型切换会重置无关字段（切 stdio→http 时清空 command/args/env）
- args 编辑：`<Textarea>` 每行一个参数，保存时 `split("\n").filter(Boolean)`
- env/headers：键值对列表，`[{k,v}]` 数组 state，Add/Delete 行

入口点：
- 设备页 sidebar section：`<McpServersEditor scope="connector" scopeId={device.id} />`
- session 侧边栏 Collapsible section（类比现有 Files section）

### i18n 键（dashboard.mcp 命名空间）

```json
"mcp": {
  "title": "MCP Servers",
  "addServer": "Add server",
  "noServers": "No MCP servers configured",
  "serverName": "Server name",
  "type": "Type",
  "command": "Command",
  "args": "Arguments (one per line)",
  "url": "URL",
  "env": "Environment",
  "headers": "Headers",
  "addEnv": "Add variable",
  "addHeader": "Add header",
  "save": "Save",
  "saving": "Saving…",
  "loadFailed": "Could not load MCP servers",
  "saveFailed": "Could not save MCP servers"
}
```

## Android 端设计

### 数据类（McpServersDtos.kt）

```kotlin
enum class McpServerType { stdio, http, sse }

data class McpServerConfig(
    val type: McpServerType,
    // stdio
    val command: String? = null,
    val args: List<String>? = null,
    val env: Map<String, String>? = null,
    // http/sse
    val url: String? = null,
    val headers: Map<String, String>? = null,
)

// 编辑草稿（UI state）
data class McpServerDraft(
    val id: String,           // 临时 uuid，用作 Compose key
    val name: String,
    val type: McpServerType,
    val command: String,      // stdio
    val argsText: String,     // 换行分隔的 args
    val env: List<Pair<String, String>>,
    val url: String,          // http/sse
    val headers: List<Pair<String, String>>,
)
```

序列化辅助：
- `JSONObject.toMcpServersMap(): Map<String, McpServerConfig>`
- `Map<String, McpServerConfig>.toJsonObject(): JSONObject`
- `McpServerDraft.toConfig(): McpServerConfig`
- `Map<String, McpServerConfig>.toDraftList(): List<McpServerDraft>`

### Sheet 结构（两个 Sheet 对称）

`ConnectorMcpServersSheet(device, onDismiss, onLoad, onSave)` / `SessionMcpServersSheet(session, onDismiss, onLoad, onSave)`

UI 结构（复用 DeviceAgentSettingsSheet 模板）：
```
ModalBottomSheet
  ├── Handle pill
  ├── Header: "MCP Servers" + X 关闭按钮
  ├── Body (scrollable Column, heightIn max 65% screen)
  │    ├── [Loading] / [Error] / [Content]
  │    └── [Content]:
  │         ├── forEach draft: ServerCard (展开/折叠)
  │         │    ├── Header: name TextField + delete button
  │         │    ├── Type row: 3-tab segmented (stdio | http | sse)
  │         │    ├── [if stdio] command TextField
  │         │    ├── [if stdio] argsText TextField (multiline)
  │         │    ├── [if stdio] env key-value list + Add variable
  │         │    ├── [if http/sse] url TextField
  │         │    └── [if http/sse] headers key-value list + Add header
  │         └── "Add server" text button
  └── Footer: "Save" SheetTextButton
```

每个 ServerCard 默认展开（新增时自动滚动到底部）。

### 入口点

- `DeviceDetailScreen.kt`：在"Agent settings"按钮旁（或下方）添加"MCP Servers"按钮（`SheetTextButton(primary=false)`），点击 `showMcpSheet = true`
- `AgentsAnywhereApp.kt`：session detail 区域添加对应 Sheet 入口（和 fork/delete/tag 回调同级）或在 `SessionDetailScreen.kt` 添加 FAB/菜单项

### Palette

与 DeviceAgentSettingsSheet 相同的 dark/light palette 模式，无需新颜色。

## 验证逻辑

保存前校验（两端）：
- 每个 server 的 name 非空
- name 在列表中唯一
- type=stdio 时 command 非空
- type=http/sse 时 url 非空
- env/headers 的 key 非空（value 可空）

前端展示错误提示，不调用 API。

## 已知约束

- Android JSONObject 无原生支持嵌套 Map 序列化，需手写辅助函数
- args 用换行编辑是简化方案（避免动态 row 列表的复杂性），可接受
- session 级别 MCP 不展示合并后的有效值（避免 UX 混淆），只显示 session 级自己的配置
