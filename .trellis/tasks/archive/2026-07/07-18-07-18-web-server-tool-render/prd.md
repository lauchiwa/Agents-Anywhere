# PRD：Web 工具卡 UI 精化

## 背景

Web 时间线中的 `type: "tool"` 条目已有基础渲染（可折叠卡片），但以下 kind 的图标和详情面板体验缺失或粗糙：

- `web_search`：用通用 Hammer 图标；detail 只显示 outputText，`url` 字段不展示
- `mcp`：用通用 Hammer 图标；arguments+result 已有展示，但服务器/工具名称只在标题行
- `tool_search`：用通用 Hammer 图标
- `schedule_wakeup`：用通用 Hammer 图标；有 delay/reason/prompt 字段但 prompt 未渲染
- `tool`（fallback）：无专属图标，直接 JSON fallback

## 目标

在不改动 connector 的前提下，仅优化 `web-next/src/components/session/session-tool-cards.tsx` 中的：
1. `ToolIcon` — 为每种 kind 配专属图标
2. `ToolDetailPanel` — 为 `web_search` 展示 url 和结果；为 `schedule_wakeup` 展示 prompt
3. `web_search` detail：展示 url 链接（如果有）+ outputText

## 验收标准

- [ ] `web_search` kind：使用 Globe 图标；detail 面板在 outputText 上方显示 url 链接（可选）
- [ ] `mcp` kind：使用 Plug 或 Cpu 图标（区别于 Hammer）
- [ ] `tool_search` kind：使用 Search 图标
- [ ] `schedule_wakeup` kind：使用 Clock 图标；detail 面板显示 prompt（如果有）
- [ ] `task_stop` kind：使用 OctagonX 或 StopCircle 图标
- [ ] `tool`（fallback）：保持 Hammer，无需改变
- [ ] 现有 `command`、`file_change` 渲染不退化
- [ ] 无 TypeScript 类型错误（`pnpm tsc --noEmit` 通过）

## 范围约束

- **仅修改** `session-tool-cards.tsx`（以及 `session-timeline-entry.tsx` 如需引入新 icon import）
- **不修改** connector 代码
- **不新增** i18n key（标题已有，detail label 用英文 literal 即可）
- **不引入** 新依赖（lucide-react 图标全部已有）

## 不在范围内

- `server_tool_use`/`server_tool_result` 的 connector 接入（需要另立任务）
- Android 侧工具渲染
- WebSearch 结果列表分条渲染（outputText 已够用）
