# Plan Mode 出口修复：ExitPlanMode 批准后设置 pending_permission_mode

## 背景与 Bug

`_SdkSessionRuntime` 有一个 `pending_permission_mode` 字段（sdk_adapter.py L120），设计用途：当用户批准 `ExitPlanMode` 工具调用后，记录要切回的执行模式（如 `acceptEdits`），下次 `session.updated` 事件携带该值通知服务端，服务端持久化到 session 的 runtime-settings override，使后续 turn 以执行模式运行。

**Bug**：`pending_permission_mode` 从未被赋值——字段存在、读写逻辑存在（L1009-1014），但在 `_can_use_tool`（L1180+）批准 `ExitPlanMode` 时，没有任何代码设置该字段。计划模式退出后，服务端不会收到新的 permissionMode，session 仍卡在 `plan` 模式。

## 根因

`_can_use_tool` (L1223-1233) 批准工具时走通用路径，没有对 `ExitPlanMode` 做特殊处理。

## 修复方案

在 `_can_use_tool` 批准逻辑（`if status in {"approved", "approved_for_session"}`）之前，增加对 `ExitPlanMode` 的检测：

```python
if tool_name == "ExitPlanMode" and status in {"approved", "approved_for_session"}:
    # ExitPlanMode input carries the target permissionMode the CLI wants to
    # switch to (e.g. "acceptEdits"). Store it so the next session.updated
    # carries permissionMode and the server can persist it as the override.
    exit_mode = _optional_string(input_data.get("permissionMode"))
    if exit_mode:
        runtime.pending_permission_mode = exit_mode
```

`ExitPlanMode` 的 `input_data` 中应有 `permissionMode` 字段（CLI 注入）。若字段不存在（防御），fallback 到 `"acceptEdits"`（计划模式的标准执行退出模式）。

## Requirements

1. 用户批准 `ExitPlanMode` 工具后，`runtime.pending_permission_mode` 被设置为 `input_data["permissionMode"]`（或 fallback `"acceptEdits"`）。
2. 下次 `_emit_session_updated` 调用时，`session.updated` 通知携带 `permissionMode` 字段。
3. 服务端 `connector_ingress.py` 已有处理逻辑（L520-530），无需改动。
4. 新增 connector 单元测试覆盖此修复。

## Acceptance Criteria

- [ ] `connector/tests/test_claude_sdk_adapter.py` 新增测试：
  - `test_exit_plan_mode_approval_sets_pending_permission_mode`：批准 `ExitPlanMode` 后，`runtime.pending_permission_mode` 被正确设置。
  - `test_exit_plan_mode_fallback_to_accept_edits`：`ExitPlanMode` input 无 permissionMode 时，fallback 为 `"acceptEdits"`。
- [ ] `cd connector && uv run pytest` 全部通过。
- [ ] `cd server && uv run pytest` 全部通过（无改动，确认无回归）。

## 范围外

- Plan Mode 的进入逻辑（已正常工作）
- Web/Android UI（已有"等待批准"提示，无需改动）
