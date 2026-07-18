# 解析 attachment 通道时间线渲染（skill_listing + deferred_tools_delta）

## Goal

attachment 是 JSONL transcript 的独立顶层字段（`attachment` key，非 `message` key），SDK `get_session_messages()` 会过滤掉这些条目，connector 的 history_adapter 完全看不到它们。当前有实际价值的 attachment 类型：

| 类型 | 数量 | 内容 |
|------|------|------|
| `skill_listing` | 50 | 可用 skill 列表（文本格式，name: description） |
| `deferred_tools_delta` | 39 | deferred 工具增删列表（addedNames/removedNames） |
| `invoked_skills` | 9 | 本次调用的 skill 名称+内容 |
| `task_reminder` | 483 | 待办提醒——**但实测全为空**（content:[], itemCount:0），暂不做 |
| `hook_additional_context` | 183 | hook 注入的上下文（附加系统消息，不适合渲染进时间线） |

**重新优先级**：`task_reminder` 全空无价值；`skill_listing` + `deferred_tools_delta` + `invoked_skills` 有实际内容，做这三个。

## Requirements

### 连接器 — history_adapter 补丁
- `_get_session_messages()` → SDK 过滤了 attachment 条目，需要**补充读取原始 JSONL** 以提取 attachment 列表
- 每个 attachment 与所属 message UUID（`parentUuid` 字段）关联
- 三种目标子类型各归一为对应 system timeline item：
  - `skill_listing` → `type:system, content.kind:"skill_listing", content.skills:[{name, description}]`（解析文本行 `- name: desc`）
  - `deferred_tools_delta` → `type:system, content.kind:"deferred_tools_delta", content.addedNames:[], content.removedNames:[]`
  - `invoked_skills` → `type:system, content.kind:"invoked_skills", content.skills:[{name, path}]`
- 其余 attachment 子类型静默忽略（不做也不报错）
- **仅 history 路径**：attachment 不出现在 live SDK stream，live 路径无需改动
- attachment item 的 orderSeq 跟在同一 turn 的最近 user message 之后（因 attachment 属于 user prompt 的系统注入上下文）

### 连接器 — timeline_reducer
- 对三种新 `blockType`（`skill_listing` / `deferred_tools_delta` / `invoked_skills`）各加 reduce 分支，产出 `type:system` timeline item

### 连接器 — 测试
- history_adapter：解析 attachment 条目 + 忽略空 task_reminder + 忽略未知子类型
- timeline_reducer：三种 blockType reduce 输出正确字段

### Web — session-timeline-entry.tsx
- `SystemCard` 新增三种 `kind` 分支：
  - `skill_listing`：折叠列表，显示 `skills[].name` + 描述（截断至 60 字符）
  - `deferred_tools_delta`：简单文本行显示 "+N deferred tools available"（addedNames.length）
  - `invoked_skills`：显示调用了哪些 skills（names 列表）
- 无需 i18n（文案直接硬编码英文，与 server-info 的 SlashCommands 一致）

### Android
- 暂不做（attachment 展示是 UI 信息，Web 先上，Android 单独任务）

## Acceptance Criteria

- [ ] `skill_listing` 类型 attachment 通过 history_adapter 出现在 timeline，显示 skill 名称列表
- [ ] `deferred_tools_delta` 类型显示新增工具数量
- [ ] `invoked_skills` 类型显示调用的 skill 名称
- [ ] `task_reminder` 和其他未知子类型不报错、不出现在 timeline
- [ ] connector pytest 全绿（含新测试）
- [ ] web tsc 通过

## Constraints

- **JSONL 直接读取**：SDK `get_session_messages()` 过滤掉 attachment，必须补充直接 parse JSONL 文件（SDK 已有 `get_session_info()` 提供目录路径）
- **仅 history path**：live stream 无 attachment，不改 sdk_adapter.py receive loop
- **最小覆盖**：只做三种子类型，其余静默忽略；task_reminder content 全空不值得实现
- **不改 server/web API 层**：attachment timeline item 走现有 system item 广播链路

## Notes

真实 JSONL attachment 条目顶层结构（与 message 条目并列，不是 message.content 的 block）：
```json
{
  "parentUuid": "...",
  "isSidechain": false,
  "attachment": {
    "type": "skill_listing",
    "content": "- name: description\n- name2: description2",
    "skillCount": 2,
    "isInitial": true,
    "names": ["name", "name2"]
  },
  "type": "attachment",
  "uuid": "...",
  "session_id": "...",
  ...
}
```
