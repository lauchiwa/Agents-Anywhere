# PRD: Web 端 session.fork UI

## Background

`session.fork` RPC 已在 connector / server / web api.ts 全链路实现（commit fe156b8）。
现需要在 Web 会话列表右键菜单中暴露该操作，让用户能 fork 当前会话到新会话并自动跳转。

## Goals

- 在会话列表每个会话的 ContextMenu 中增加"Fork 会话"菜单项
- 调用 `api.forkSession` → 获得新 `sessionId` → 导航到新会话
- Fork 期间显示 loading 状态，避免重复点击
- Fork 失败时 toast 提示

## Non-Goals

- Android 端（独立任务）
- Fork 时指定 `upToMessageId`（高级功能，后续迭代）
- Fork 时修改标题（用户可以事后 rename）

## User Story

用户在会话列表右键某会话 → 点击"Fork 会话" → 短暂 loading → 跳转到新会话（内容与原会话一致）。

## Acceptance Criteria

1. `app-sidebar.tsx` 会话 ContextMenu 新增"Fork"菜单项，位于"Rename"之后。
2. 点击后调用 `workspace-context` 暴露的 `forkSession(id)` 方法。
3. `forkSession` 在 `workspace-context.tsx` 实现：调用 `api.forkSession`，成功后 refetch 会话列表并导航到新 sessionId。
4. Fork 进行中：该菜单项 disabled（forking 状态）。
5. Fork 失败：toast 错误提示（复用现有 toast 模式）。
6. i18n：`en.json` / `zh-CN.json` 新增 `dashboard.sessions.fork` 键。
7. TypeScript 无新 error（`tsc --noEmit` 通过）。

## Key Files

- `web-next/src/components/app-sidebar.tsx` — ContextMenu 入口
- `web-next/src/components/workspace-context.tsx` — `forkSession` action 实现
- `web-next/src/features/dashboard/api.ts` — `forkSession` RPC（已存在）
- `web-next/messages/en.json` / `zh-CN.json` — i18n

## Implementation Notes

- 参照 `renameSession` 的调用链：`app-sidebar` → `workspace-context.renameSession` → `api.renameSession`
- `api.forkSession` 签名（已有）：`forkSession(token, sessionId, externalSessionId, cwd?, upToMessageId?, title?)`
  - `externalSessionId`：从 session 对象取
  - `cwd`：可选，从 session 对象取
- 新 sessionId 从 RPC 响应的 `result.sessionId` 中取
- 导航用现有 router/navigate 跳转到新 session
