# skills / ToolSearch / 延迟工具处理

## Goal

为本 CLI 变体独有的"延迟工具检索"机制提供专门的时间线处理与渲染。当前 `ToolSearch` 工具走通用 `tool_call` 路径,配套的 `deferred_tools_delta` / `skill_listing` 等 attachment 完全不被连接器识别。

## 背景(调研已确认)

- 本地 43 个 JSONL 实证:
  - `ToolSearch` 工具出现 10 次,input 形如 `{"max_results":3,"query":"select:TaskStop"}` —— 用于按需检索并加载延迟工具。
  - attachment 子类型 `deferred_tools_delta`(39 次):延迟工具增量清单,配合 ToolSearch。
  - attachment 子类型 `skill_listing`(50 次):可用技能清单注入。
- SDK 侧:`ClaudeAgentOptions.skills: list[str] | "all" | None`;设了之后 SDK 自动把 `"Skill"` 加进 allowed_tools。context usage 响应里有独立 `skills` 分类。
- 连接器 `normalizers.py` 目前只处理 text/tool_use/tool_result/thinking 四种 block,**完全不解析 attachment 顶层类型**(attachment 在历史里共 1007 条,是最大的未覆盖面)。

## Requirements

- 明确本任务范围:是仅让 `ToolSearch` 工具卡片有更贴切的展示(轻量),还是要解析 attachment 层的 `deferred_tools_delta` / `skill_listing`(重,牵涉 attachment 通道从零搭建)。
- 若做 ToolSearch 卡片:给它一个可读的 kind/展示(检索词 + 命中的工具),而非裸 JSON。
- 若做 skills:决定是否暴露 `ClaudeAgentOptions.skills` 配置,以及 skill_listing 注入是否需要在客户端展示。
- 与 [[07-15-connector-agent-options-passthrough]](skills 属于 Options 字段)划清边界,避免重复。

## Acceptance Criteria

- [ ] ToolSearch 工具调用在时间线有可读展示(不是原始 tool_call JSON)。
- [ ] (若纳入 attachment)`deferred_tools_delta` / `skill_listing` 至少不再被静默丢弃,或有明确的处理决策记录在案。
- [ ] 连接器测试通过,新增对应覆盖。
- [ ] 无回归。

## Notes

- 优先级 P3。attachment 通道是一块独立的大工程,建议先只做 ToolSearch 卡片这一最小改进,attachment 解析另开任务。
- 关联梯队:第四梯队(高级特性)。
- skills 的 Options 配置与本任务有交集,实现前先确认归属。
