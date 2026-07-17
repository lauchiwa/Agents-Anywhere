# PRD: Web 端 session.delete UI

## Background

`session.delete` RPC 已在 connector / server / web api.ts 全链路实现（commit fe156b8）。
现需要在 Web 会话列表右键菜单中暴露删除操作，并在删除前弹出确认对话框。

## Goals

- 在会话 ContextMenu 新增"删除会话"菜单项（危险色）
- 删除前弹出确认 Dialog，防止误操作
- 删除成功后：从会话列表移除该会话；若当前正在查看该会话，导航到列表首页

## Non-Goals

- 软删除 / 回收站（直接硬删除，与 SDK 行为一致）
- Android 端（独立任务）

## User Story

用户右键会话 → 点击"删除" → 确认对话框 → 确认后会话从列表消失，若当前在该会话则跳回列表。

## Acceptance Criteria

1. `app-sidebar.tsx` ContextMenu 新增"删除"菜单项，使用危险色（`text-destructive`），位于末尾并加分隔线。
2. 点击后弹出 `AlertDialog` 确认框（复用 shadcn `AlertDialog`）。
3. 确认后调用 `workspace-context` 暴露的 `deleteSession(id)` 方法。
4. `deleteSession` 实现：调用 `api.deleteSession`，成功后 refetch 会话列表；若删除的是当前活跃会话则导航回列表。
5. 删除失败：toast 错误提示。
6. i18n：`en.json` / `zh-CN.json` 新增 `dashboard.sessions.delete`、`dashboard.sessions.deleteConfirmTitle`、`dashboard.sessions.deleteConfirmDesc` 键。
7. TypeScript 无新 error（`tsc --noEmit` 通过）。

## Key Files

- `web-next/src/components/app-sidebar.tsx` — ContextMenu + AlertDialog
- `web-next/src/components/workspace-context.tsx` — `deleteSession` action
- `web-next/src/features/dashboard/api.ts` — `deleteSession` RPC（已存在）
- `web-next/messages/en.json` / `zh-CN.json` — i18n
