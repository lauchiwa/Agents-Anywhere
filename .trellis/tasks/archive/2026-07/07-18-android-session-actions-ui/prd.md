# PRD: Android 端 session.fork / delete / tag UI

## Background

Web 端已完成 session.fork、session.delete、session.tag 三个操作（通过上下文菜单实现）。Android 端目前的长按菜单（`HomeSessionActionMenuCard`）只有 Rename / Archive / Pin 三项，缺少 Fork / Delete / Set Tag。

服务端 API 已就绪：
- `POST /sessions/{session_id}/fork` → `RpcResponsePayload`
- `POST /sessions/{session_id}/delete` → `RpcResponsePayload`
- `POST /sessions/{session_id}/tag` body `{tag: string|null}` → `RpcResponsePayload`

## Requirements

### 1. `AgentSession` 扩展
- 新增字段 `val tag: String? = null` 和 `val externalSessionId: String? = null`

### 2. `RemoteSession` 扩展
- `RemoteSession` 新增 `val tag: String? = null` 字段
- `SessionsApi.toRemoteSession()` 中补充 `tag = optNullableString("tag")`

### 3. `RemoteSession` → `AgentSession` 映射
- `SessionsController.toAgentSession()` 中补充 `tag` 和 `externalSessionId` 映射

### 4. `SessionsApi` 新增三个方法
- `forkSession(serverUrl, authorizationToken, sessionId): RemoteRpcResponse`
  - `POST /sessions/{sessionId}/fork` body `{}`
- `deleteSession(serverUrl, authorizationToken, sessionId): RemoteRpcResponse`
  - `POST /sessions/{session_id}/delete` body `{}`
- `tagSession(serverUrl, authorizationToken, sessionId, tag: String?): RemoteRpcResponse`
  - `POST /sessions/{session_id}/tag` body `{tag: <string or null>}`

### 5. `SessionsController` 新增三个公开方法
- `forkSession(sessionId, devices): Result<Unit>` — 调用 fork API，成功后触发 reload（fork 返回 RpcResponse 不含完整 session）
- `deleteSession(sessionId, devices): Result<Unit>` — 调用 delete API
- `tagSession(sessionId, tag: String?, devices): Result<Unit>` — 调用 tag API

### 6. `HomeSessionActionMenuCard` 扩展
增加三行：
- **Fork** — 图标 `ic_session_action_fork`（暂用已有图标 fallback）
- **Set Tag** — 图标 `ic_session_action_tag`
- **Delete** — 图标 `ic_session_action_delete`（红色文字表示破坏性操作）

菜单高度从 168dp 扩展到 280dp（6 行 × ~46dp）。

### 7. HomeScreen 参数扩展
- `HomeScreen` 新增三个 callback 参数：
  - `onForkSession: suspend (String) -> Result<Unit>`
  - `onDeleteSession: suspend (String) -> Result<Unit>`
  - `onTagSession: suspend (String, String?) -> Result<Unit>`
- 新增 dialog 状态：`taggingSession: AgentSession?` 和 `deletingSession: AgentSession?`
- `HomeSessionActionOverlay` 透传新三个 callback
- 新增 `HomeTagSessionDialog` composable（类似 `HomeRenameSessionDialog`）
- 新增 delete 确认 `AlertDialog`

### 8. AgentsAnywhereApp 接线
- 在 `AgentsAnywhereApp.kt` 为三个新 callback 提供实现

### 9. 字符串资源
在 `strings.xml` 新增：
- `home_fork`, `home_fork_success`, `home_fork_failed`
- `home_delete`, `home_delete_confirm_title`, `home_delete_confirm_message`, `home_delete_success`, `home_delete_failed`
- `home_set_tag`, `home_tag_placeholder`, `home_tag_success`, `home_tag_failed`

## Constraints
- 不引入第三方依赖
- API 调用均在 `Dispatchers.IO` 中执行
- fork 成功后触发 `loadSessions()` reload，不做本地 diff
- tag 做乐观更新：controller 返回 `Result<Unit>`，HomeScreen 用乐观 reload 刷新

## Acceptance Criteria
- [ ] 长按 session 弹出的菜单包含 Fork / Set Tag / Delete 三项
- [ ] Fork 点击后 sessions 列表刷新，出现新 session；错误时 toast 错误
- [ ] Set Tag 打开 dialog，保存后 toast 成功
- [ ] Delete 点击弹出确认 dialog，确认后 session 从列表消失；错误时 toast
- [ ] 所有错误均通过 toast 展示
