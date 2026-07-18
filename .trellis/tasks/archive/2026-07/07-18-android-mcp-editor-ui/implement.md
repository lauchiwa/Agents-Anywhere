# Implement: MCP Server 配置编辑器

## 执行顺序

### Phase 1：Web 基础层

- [ ] **1.1** `web-next/src/features/dashboard/types.ts`
  - 添加 `McpServerType`、`McpServerConfig`、`McpServersMap` 类型定义
  
- [ ] **1.2** `web-next/src/lib/api.ts`
  - 添加 `getConnectorMcpServers(connectorId)` → GET `/api/connectors/{id}/mcp-servers`
  - 添加 `putConnectorMcpServers(connectorId, servers)` → PUT（body: `{ mcpServers }`）
  - 添加 `getSessionMcpServers(sessionId)` → GET `/api/sessions/{id}/mcp-servers`
  - 添加 `putSessionMcpServers(sessionId, servers)` → PUT（body: `{ mcpServers }`）

- [ ] **1.3** 验证：`tsc --noEmit` 无错

### Phase 2：Web 编辑器组件

- [ ] **2.1** 新建 `web-next/src/components/mcp-servers-editor.tsx`
  - Props: `scope: "connector" | "session"`, `scopeId: string`, `readOnly?: boolean`
  - `useQuery` 读取，`useMutation` 保存
  - 本地草稿状态：`McpServerDraft[]`（含临时 `_id: crypto.randomUUID()`）
  - 类型切换时清理无关字段
  - env/headers 动态键值对行（Add / Delete）
  - 保存前校验（name 唯一非空、stdio command、http/sse url）
  - 错误行内展示（不用 toast）

- [ ] **2.2** `web-next/messages/en.json` — 添加 `dashboard.mcp.*` 键
- [ ] **2.3** `web-next/messages/zh-CN.json` — 同上中文翻译
- [ ] **2.4** 验证：`tsc --noEmit` 无错

### Phase 3：Web 入口接入

- [ ] **3.1** 设备详情页（找到 device detail 组件，可能是 `DevicePage` 或 sidebar）
  - 添加 MCP Servers section，使用 `<McpServersEditor scope="connector" scopeId={device.id} />`
  
- [ ] **3.2** Session 侧边栏（`session-detail.tsx` 或 sidebar 组件）
  - 添加 collapsible MCP Servers section，使用 `<McpServersEditor scope="session" scopeId={session.id} />`

- [ ] **3.3** 验证：`tsc --noEmit` 无错，dev server 可打开设备页和 session 页，无 console 错误

### Phase 4：Android 基础层

- [ ] **4.1** 新建 `android/app/src/main/java/com/agentsanywhere/app/api/McpServersDtos.kt`
  - `McpServerType` enum
  - `McpServerConfig` data class
  - `McpServerDraft` data class（UI 草稿状态）
  - `JSONObject.toMcpServersMap()` 扩展函数
  - `Map<String, McpServerConfig>.toJsonObject()` 扩展函数
  - `McpServerDraft.toConfig()` 转换函数
  - `Map<String, McpServerConfig>.toDraftList()` 转换函数（生成临时 UUID）

- [ ] **4.2** `android/.../api/DevicesApi.kt`
  - 添加 `getConnectorMcpServers(serverUrl, authToken, connectorId): Map<String, McpServerConfig>`
  - 添加 `putConnectorMcpServers(serverUrl, authToken, connectorId, servers): Map<String, McpServerConfig>`

- [ ] **4.3** `android/.../api/SessionsApi.kt`
  - 添加 `getSessionMcpServers(serverUrl, authToken, sessionId): Map<String, McpServerConfig>`
  - 添加 `putSessionMcpServers(serverUrl, authToken, sessionId, servers): Map<String, McpServerConfig>`

- [ ] **4.4** `android/.../feature/devices/DevicesController.kt`（或等价位置）
  - 添加 `suspend fun getConnectorMcpServers(connectorId): Result<Map<String, McpServerConfig>>`
  - 添加 `suspend fun putConnectorMcpServers(connectorId, servers): Result<Map<String, McpServerConfig>>`

- [ ] **4.5** `android/.../feature/sessions/SessionsController.kt`
  - 添加 `suspend fun getSessionMcpServers(sessionId): Result<Map<String, McpServerConfig>>`
  - 添加 `suspend fun putSessionMcpServers(sessionId, servers): Result<Map<String, McpServerConfig>>`

- [ ] **4.6** 验证：`./gradlew :app:compileDebugKotlin` 无错

### Phase 5：Android Sheets

- [ ] **5.1** 新建 `ConnectorMcpServersSheet.kt`
  - `ModalBottomSheet`，`skipPartiallyExpanded=true`，圆角 28dp
  - `LaunchedEffect` 触发 `onLoadMcpServers`，loading/error/content 三态
  - 草稿 state：`var drafts by remember { mutableStateOf(listOf<McpServerDraft>()) }`
  - ServerCard（展开/折叠）：name field + type segmented control + 条件字段 + env/headers 键值对列表
  - "Add server" 按钮（追加空草稿，`LazyColumn` 滚到底）
  - Footer：Save `SheetTextButton(primary=true)`，调用 `onSaveMcpServers`
  - Palette：复用 `DeviceAgentSettingsSheet` 同款 dark/light palette 模式

- [ ] **5.2** 新建 `SessionMcpServersSheet.kt`
  - 结构与 ConnectorMcpServersSheet 对称，props 用 `session: AgentSession`
  
- [ ] **5.3** 验证：`compileDebugKotlin` 无错

### Phase 6：Android 入口与字符串

- [ ] **6.1** `strings.xml` + `values-zh-rCN/strings.xml`
  - 添加所有 `connector_mcp_*` / `session_mcp_*` 键（参考 prd 中的键列表）

- [ ] **6.2** `DeviceDetailScreen.kt`
  - 在 AgentSettings 按钮附近添加"MCP Servers"按钮（`SheetTextButton(primary=false)` 或 `RoundIconAction`）
  - `var showMcpSheet by remember { mutableStateOf(false) }`
  - 条件渲染 `ConnectorMcpServersSheet`
  - 回调：`onLoadMcpServers = { devicesController.getConnectorMcpServers(device.id) }`
  - 回调：`onSaveMcpServers = { servers -> devicesController.putConnectorMcpServers(device.id, servers) }`

- [ ] **6.3** `AgentsAnywhereApp.kt` 或 `SessionDetailScreen.kt`
  - 类比 fork/delete/tag 的方式添加 session MCP sheet 入口（toolbar 菜单项或 Session settings 区域）

- [ ] **6.4** 验证：`compileDebugKotlin` 无错

### Phase 7：端到端验证

- [ ] `cd web-next && npx tsc --noEmit` 无错
- [ ] `cd android && ./gradlew :app:compileDebugKotlin` 无错
- [ ] `cd server && python -m pytest tests/ -x -q` 无回归（server 无改动，理论上通过）
- [ ] `cd connector && python -m pytest tests/ -x -q` 无回归（connector 无改动）

## 回滚点

- Web 完全独立于 Android，可分阶段提交
- Phase 1-3（Web）和 Phase 4-6（Android）互相无依赖，可并行
- 每个 Phase 末尾验证通过才进入下一阶段

## 关键实现细节

### Web：args 编辑

```typescript
// 编辑时
argsText: (config.args ?? []).join("\n")

// 保存时
args: draft.argsText.split("\n").map(s => s.trim()).filter(Boolean)
```

### Android：JSON 序列化辅助

```kotlin
// JSONObject → McpServerConfig
fun JSONObject.toMcpServerConfig(): McpServerConfig {
    val type = McpServerType.valueOf(getString("type"))
    return when (type) {
        McpServerType.stdio -> McpServerConfig(
            type = type,
            command = optString("command").ifEmpty { null },
            args = optJSONArray("args")?.let { arr -> (0 until arr.length()).map { arr.getString(it) } },
            env = optJSONObject("env")?.toStringMap(),
        )
        McpServerType.http, McpServerType.sse -> McpServerConfig(
            type = type,
            url = optString("url").ifEmpty { null },
            headers = optJSONObject("headers")?.toStringMap(),
        )
    }
}

// Map<String,String> helper
fun JSONObject.toStringMap(): Map<String, String> =
    keys().asSequence().associateWith { getString(it) }
```

### Android：segmented control（类型切换）

参考现有 DeviceAgentSettingsSheet 中的 Row + border 实现，或复用 `AndroidApp` 里任意现有 segmented/tab 控件，保持视觉一致。
