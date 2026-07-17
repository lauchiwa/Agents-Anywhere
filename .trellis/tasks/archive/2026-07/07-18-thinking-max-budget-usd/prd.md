# PRD: thinking.max_budget_usd passthrough

## Background

Claude Agent SDK 支持 `ClaudeAgentOptions.thinking.max_budget_usd`，限制单次会话的 thinking token 花费上限。
当前 connector 在构建 `ClaudeAgentOptions` 时未透传该参数；用户无法通过 Agents-Anywhere 控制 thinking 预算。

## Goals

- 在启动会话（`turn.start` / `ClaudeAgentOptions` 构建）时支持透传 `thinking.max_budget_usd`
- Web/Android 端启动会话时可选择性传入该参数

## Non-Goals

- UI 层的"thinking 预算"设置界面（可作为后续迭代；本任务只做 passthrough，验证端到端链路即可）
- `thinking.budget_tokens` 独立控制（现有逻辑已处理）

## User Story

开发者通过 API / web 启动会话时，可在 session 参数中传入 `thinkingMaxBudgetUsd: 0.5`，connector 将其透传给 SDK，从而限制该会话的 thinking 花费。

## Acceptance Criteria

1. `connector/connector/claude/sdk_adapter.py` 的 `ClaudeAgentOptions` 构建逻辑中，读取 `params.get("thinkingMaxBudgetUsd")` 并透传给 `thinking.max_budget_usd`（若 SDK 支持）。
2. 使用 `getattr` 或版本判断防御性处理，避免旧 SDK 版本报错。
3. server `turn.start` handler 透传该字段（`SessionRunService` / RPC params）。
4. web `api.ts` `startTurn` 支持可选 `thinkingMaxBudgetUsd` 参数。
5. 单元测试覆盖：传入值正确透传给 SDK options；不传时不影响现有行为。
6. TypeScript 无新 error（`tsc --noEmit` 通过）。

## Key Files

- `connector/connector/claude/sdk_adapter.py` — options 构建
- `server/agent_server/services/session_run.py` — turn.start 参数透传
- `web-next/src/features/dashboard/api.ts` — startTurn 参数扩展
- `connector/tests/test_claude_sdk_adapter.py` — 单元测试

## Notes

- 先查 SDK `ClaudeAgentOptions` 是否有 `thinking.max_budget_usd` 字段（0.2.121），确认后实现。
