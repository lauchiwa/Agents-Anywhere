# PRD: Web 端 session.tag UI

## Background

`session.tag` RPC 已在 connector / server / web api.ts 全链路实现（commit 85c5946）。
现需要在 Web 会话列表中暴露打标签 / 清除标签的入口。

## Goals

- 在会话 ContextMenu 新增"设置标签"菜单项
- 点击后弹出 Popover/Dialog，允许用户输入任意标签文字或清空标签
- 标签显示在会话列表项上（小 badge）

## Non-Goals

- 标签过滤 / 搜索（后续迭代）
- Android 端（独立任务）
- 预设标签列表（自由文本即可）

## User Story

用户右键会话 → "设置标签" → 弹出输入框（预填当前标签）→ 修改并确认 → 会话列表项显示新标签 badge；清空输入则清除标签。

## Acceptance Criteria

1. `app-sidebar.tsx` ContextMenu 新增"设置标签"菜单项，位于"Fork"之后。
2. 点击后弹出内联输入（或小 Dialog），预填当前 `session.tag`（若有）。
3. 确认后调用 `workspace-context` 暴露的 `tagSession(id, tag | null)` 方法。
4. `tagSession` 实现：调用 `api.tagSession`，成功后 refetch 会话列表（或乐观更新）。
5. 会话列表项显示标签 badge（若 `session.tag` 非空）。
6. 输入框留空并确认 → 传 `null` → 清除标签。
7. i18n：新增 `dashboard.sessions.setTag`、`dashboard.sessions.tagPlaceholder` 键。
8. TypeScript 无新 error（`tsc --noEmit` 通过）。

## Key Files

- `web-next/src/components/app-sidebar.tsx` — ContextMenu + 标签输入 UI
- `web-next/src/components/workspace-context.tsx` — `tagSession` action
- `web-next/src/features/dashboard/api.ts` — `tagSession` RPC（已存在）
- `web-next/messages/en.json` / `zh-CN.json` — i18n

## Notes

- 先确认 server Session 模型 / list 返回中是否含 `tag` 字段；如无，需同步补充。
