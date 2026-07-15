# ScheduleWakeup / TaskStop 工具专门处理

## Goal

为本 CLI 变体独有的两个工具 `ScheduleWakeup`(定时唤醒)与 `TaskStop`(停止子代理任务)提供贴切的时间线语义与展示。当前两者都走通用 `tool_call` 路径,显示为裸 JSON,用户看不懂发生了什么。

## 背景(调研已确认)

- 本地 43 个 JSONL 实证:
  - `ScheduleWakeup` 出现 2 次,input 形如 `{"delaySeconds":120,"prompt":"检查 Windows 打包后台任务结果","reason":"等待外部构建"}` —— 让 agent 在指定延迟后自我唤醒继续任务。
  - `TaskStop` 出现 2 次 —— 停止某个正在运行的子代理任务。
- 连接器 `timeline_reducer.py` 的 `_tool_kind`(第 152 行)对这两个工具名无特判,落入默认 `kind:"tool"`,`_tool_call_content` 只透传裸 arguments。
- 注意 `is_task_event_tool_name`(reducer.py:166)只隐藏 `TaskCreate`/`TaskUpdate` 这类 bookkeeping 工具(名字以 Task 开头且第 5 字符大写),`TaskStop` 也匹配这个规则 —— **需确认 TaskStop 是否被误当 bookkeeping 隐藏掉**,这可能是本任务要修的一个隐藏 bug。

## Requirements

- 核实 `TaskStop` 是否被 `is_task_event_tool_name` 误过滤(`"TaskStop"` → 第 5 字符 `S` 大写 → 会被隐藏)。若确实被隐藏,决定它应否可见,并修正规则。
- 为 `ScheduleWakeup` 提供可读展示:延迟时长 + 唤醒原因 + prompt 摘要,而非裸 JSON。
- 为 `TaskStop` 提供可读展示:被停止的任务标识。
- 确认这些是否需要客户端新增卡片类型,还是复用现有 tool 卡片 + 更好的内容字段即可。

## Acceptance Criteria

- [ ] 明确并记录 `TaskStop` 当前是否被误隐藏,若是则修正。
- [ ] `ScheduleWakeup` / `TaskStop` 在时间线有可读展示。
- [ ] 连接器测试通过,新增对应覆盖(含 is_task_event_tool_name 的边界)。
- [ ] 无回归:`TaskCreate`/`TaskUpdate` 仍被正确隐藏,真正的 `Task` 子代理仍可见。

## Notes

- 优先级 P3。使用频率极低(各 2 次),但 TaskStop 的误隐藏若属实则是需要修的正确性问题,值得优先核实。
- 关联梯队:第四梯队(高级特性)。
