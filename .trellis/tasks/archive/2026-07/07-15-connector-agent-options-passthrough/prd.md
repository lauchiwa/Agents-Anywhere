# ClaudeAgentOptions 字段透传(thinking config / TaskBudget / sandbox / betas / plugins / agents)

## Goal

把一批当前完全未设置的 `ClaudeAgentOptions` 字段按需暴露为运行时可配置项。连接器 `_options_kwargs`(sdk_adapter.py:609)目前只设了 include_partial_messages / can_use_tool / stderr / hooks / cwd / resume / cli_path / permission_mode / model / effort,其余高级选项一律用 SDK 默认。

## 背景(调研已确认 SDK 0.2.116)

未透传的 Options 字段及其用途:

- `thinking: ThinkingConfig` —— Adaptive / Enabled(budget_tokens + display)/ Disabled 三选一,控制 extended thinking。配合已完成的 thinking 块渲染,可让客户端控制思考预算/开关。
- `task_budget: TaskBudget{total:int}` —— 告诉模型剩余 token 预算好收尾;另有 `max_budget_usd` 按美元封顶、`max_turns` 按轮数封顶。
- `sandbox: SandboxSettings` —— 命令执行隔离 + 文件/网络限制。安全相关,需谨慎。
- `betas: list[SdkBeta]` —— 当前枚举仅 `"context-1m-2025-08-07"`(1M 上下文)。
- `plugins: list[SdkPluginConfig]` —— 目前只支持 `type="local"` + path。
- `agents: dict[str, AgentDefinition]` —— 自定义子代理定义(description/prompt/tools/model/skills)。
- `setting_sources` —— user/project/local 过滤;`[]` 为隔离模式,含 "project" 才加载 CLAUDE.md。
- `system_prompt`(preset/file/str)、`add_dirs`、`env`、`allowed_tools`/`disallowed_tools`。

## Requirements

- 这是一个"伞形"任务,需先分诊:哪些字段值得暴露、优先级如何、各自是否该拆成独立子任务。
- 对决定纳入的字段:定义 start_turn params 到 Options 的映射,补充校验。
- `sandbox` 与 `allowed_tools`/`disallowed_tools` 涉及安全边界,单独评估,不与普通配置混做。
- `thinking` 与 thinking 渲染任务、`skills` 与 skills 任务([[07-15-connector-skills-toolsearch]])有交集,划清归属。

## Acceptance Criteria

- [ ] 产出分诊结论:每个字段"做/不做/拆子任务",附理由与优先级。
- [ ] 至少落地一批低风险高价值字段的透传(如 max_turns / thinking / betas)。
- [ ] 安全相关字段(sandbox / *_tools)若纳入,有独立的安全评估记录。
- [ ] 连接器 + 服务端测试通过;未配置时行为与现状一致(无回归)。

## Notes

- 优先级 P3。伞形任务,建议先分诊再逐字段拆分,不要一次性全做。
- 关联梯队:第四梯队(高级特性)。
- 与多个任务有字段级交集,是本批任务里最需要先规划的一个。
