# 透传 auto 权限模式与 max effort 到前端

## Goal

SDK 0.2.121 的 PermissionMode 新增 auto（模型逐工具自动批准）、EffortLevel 新增 max。连接器 _options_kwargs 已透传 permission_mode/effort，仅需 web + Android 前端选项枚举各补两个值。成本极小。

## Requirements

- TBD

## Acceptance Criteria

- [ ] TBD

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
