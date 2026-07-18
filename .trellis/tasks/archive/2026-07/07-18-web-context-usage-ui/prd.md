# PRD: Web 端 context usage 展示

## Background

`session-view-header.tsx` 中已有 `ContextUsageBadge` 组件实现（token 用量 badge +
HoverCard 详情），`get_context_usage` RPC 也已全链路实现。但 `workspace-context.tsx`
的 `mapSession` 函数未将 `contextUsage`（及 `rateLimit`）从服务端 `RealSessionView`
映射到本地 `SessionView`，导致 badge 永远接收不到数据、始终隐藏。

## Root Cause

`mapSession` 缺少以下字段：
- `contextUsage` — token 用量数据（来自 `session.updated` 通知）
- `rateLimit` — 限速状态（同上）

## Goals

- 将 `contextUsage` 和 `rateLimit` 加入 `mapSession` 的映射
- `ContextUsageBadge` 在会话有 context usage 数据时自动展示（无需其他改动）

## Non-Goals

- 修改 `ContextUsageBadge` UI（已实现且设计合理）
- 主动轮询 `get_context_usage`（数据通过 `session.updated` 推送，被动即可）
- Android 端展示（独立任务）

## Acceptance Criteria

1. `workspace-context.tsx` `mapSession` 加入 `contextUsage` 和 `rateLimit` 字段映射。
2. `demo-api.ts` `SessionView` 已有 `contextUsage` 字段；确认 `rateLimit` 字段也存在，如缺则补充。
3. 打开一个有过 token 消耗的 Claude 会话，会话头部显示 `xx% context` badge。
4. TypeScript 无新 error（`tsc --noEmit` 通过）。
5. connector + server 测试不受影响（无后端改动）。

## Key Files

- `web-next/src/components/workspace-context.tsx` — `mapSession` 函数（主改动）
- `web-next/src/lib/demo-api.ts` — `SessionView` 类型（确认 rateLimit 字段）
- `web-next/src/components/session-view-header.tsx` — `ContextUsageBadge`（只读参考）
