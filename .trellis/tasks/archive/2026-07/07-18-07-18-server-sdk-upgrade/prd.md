# server SDK 升级至 0.2.119

## Goal

将 server venv 的 claude-agent-sdk 从 0.2.116 升至与 connector 一致的 0.2.119，统一版本，为后续基于最新 SDK 全面探索新功能奠定基础。

## Requirements

- `server/uv.lock` 中 claude-agent-sdk 锁定版本 ≥ 0.2.119。
- server 现有测试套件无新失败。
- 不改动 connector 侧任何文件。

## Acceptance Criteria

- [ ] `grep "version" server/uv.lock | grep claude-agent-sdk` 显示 0.2.119+。
- [ ] `cd server && uv run pytest` 全部通过（或与升级前同等通过率）。

## Notes

- Lightweight task，PRD-only，无需 design.md / implement.md。
- server 使用 SDK 的唯一入口：`server/agent_server/claude/sdk_driver.py`。
