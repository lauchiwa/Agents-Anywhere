# Android attachment 渲染 parity：skill_listing / deferred_tools_delta / invoked_skills

## Goal

Web 侧已支持 `skill_listing` / `deferred_tools_delta` / `invoked_skills` 三种 system timeline item 渲染（commit `5139350`）。Android 端收到同样的服务端推送，但 `toSystemMessage()` fallback 取不到 `message`/`text` 字段而返回 `null`，三种 item 全部静默丢弃。本任务补齐 Android 渲染 parity。

## Background

- `skill_listing` content：`{ kind, skills: [{name, description}] }`
- `deferred_tools_delta` content：`{ kind, addedNames: [String], removedNames: [String] }`
- `invoked_skills` content：`{ kind, skills: [{name, path}] }`

## Requirements

- **skill_listing**：折叠卡片，header「N skills available」，展开列出 name + description。
- **deferred_tools_delta**：小 pill，显示「+N deferred tools」/「-N tools」或两者。
- **invoked_skills**：小 pill，显示「Skills: name1, name2」。
- 样式与 Compact/Notification 等已有卡片风格一致。
- 历史加载与实时 SSE 推送均生效（Controller 层处理）。

## Out of Scope

- `task_reminder` 不实现（服务端始终为空）。
- Web 侧无需改动。
- 不新增字符串资源（沿用硬编码英文，与已有卡片保持一致）。

## Acceptance Criteria

- [ ] `TimelineMessageKind` 新增 `SkillListing`、`DeferredToolsDelta`、`InvokedSkills` 三个枚举值。
- [ ] `toSystemMessage()` 对三个 kind 正确解析并返回非 null `TimelineMessage`。
- [ ] `SessionMessages.kt` 顶层 `when` 及子 agent `when` 均新增三个分支，各调用对应 Composable。
- [ ] 三个 Composable 正确渲染内容。
- [ ] `./gradlew :app:compileDebugKotlin` 编译通过。
