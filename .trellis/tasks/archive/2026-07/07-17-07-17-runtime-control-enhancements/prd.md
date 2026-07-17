# Runtime 控制增强：1M betas 修复 + auto 模式 + stop_task

## 背景

本任务合并三个独立但性质相近（连接器/服务端 runtime 控制层）的增强项，研究依据来自 2026-07-17 的 SDK 深挖研究（`.trellis/tasks/07-15-connector-render-output-images/research/`）。

---

## 问题 1（Bug）：`[1M]` model 后缀没有触发 betas，1M 上下文实际未启用

**根因**：`server/agent_server/core/runtime_config.py:117-123` 暴露了 `claude-opus-4-8[1M]` 等带 `[1M]` 后缀的 model 选项。但 `server/agent_server/infra/runtimes/claude/sdk_driver.py:43` 直接把原始字符串传给 SDK `model=` 字段，没有后缀剥离和 `betas` 注入。Claude SDK `model` 字段只接受真实 model ID，`[1M]` 会被当成 unknown model，`betas=["context-1m-2025-08-07"]` 从未注入。

**修法**：在 `sdk_adapter.py` 的 `_options_kwargs` 处理 model 时，检测并剥离 `[1M]` 后缀，同时注入 `betas=["context-1m-2025-08-07"]`。

## 问题 2：`auto` / `dontAsk` 权限模式未暴露给客户端

**现状**：`set_permission_mode` RPC 已能透传任意字符串（`sdk_adapter.py:259`），SDK `PermissionMode` 已含 `"auto"` 和 `"dontAsk"`。但服务端 `runtime_config.py` 的 permissionMode schema 只有 `["default","acceptEdits","bypassPermissions","plan"]`，客户端选项里没有 `auto`/`dontAsk`。

**价值**：`auto` 模式让长任务半自动跑（模型分类器自动批/拒），手机远程控制场景下无需每步点批准。`dontAsk` 拒绝所有未预批准工具（适合只读审阅场景）。

**修法**：把 `"auto"` 和 `"dontAsk"` 加进 permissionMode 的 schema 选项列表，补充对应描述文案（i18n 两端两语言）。

## 问题 3：`stop_task` RPC 缺失，TaskStop 工具卡实际停不了任务

**现状**：连接器已渲染 `TaskStop` 工具卡（用户能看到 Claude 调用了 stop），但没有用户主动触发 RPC——手机端无法主动停止一个正在跑的后台子代理任务。SDK 0.2.119 新增 `client.stop_task(task_id)` 方法（`client.py:454-475`）。

**修法**：
- 连接器 `sdk_adapter.py` 加 `stop_task(task_id)` 实现（调 `client.stop_task`）
- 连接器 `runtime.py` 加 `task.stop` RPC 分派
- 服务端 `connector_ingress.py` 加对应的 `task.stop` 下发入口
- Web 子代理进度卡（`SubagentProgressBadge`）加"停止"按钮，Android 对应位置同步

---

## Requirements

1. `[1M]` model 后缀被自动剥离，同时注入 `betas=["context-1m-2025-08-07"]`；非 `[1M]` 型号不注入 betas。
2. permissionMode 选项新增 `auto`（自动批准）和 `dontAsk`（全拒）；文案清晰描述行为差异；i18n 两端两语言补齐。
3. `task.stop` RPC 全链贯通：用户能从 Web/手机的子代理进度卡主动停止子任务。
4. 以上三项改动均有测试覆盖（连接器 + 服务端）。

## Acceptance Criteria

- [ ] 选 `[1M]` 后缀型号发 turn，SDK 收到剥离后的真实 model ID + `betas=["context-1m-2025-08-07"]`；选普通型号不注入 betas。
- [ ] permissionMode 下拉含 `auto` / `dontAsk`；切换后 `set_permission_mode` 正确透传 SDK。
- [ ] Web 子代理进度卡有"停止"按钮；点击后连接器调 `client.stop_task`；SDK 无 active client 时降级提示。
- [ ] 连接器测试套件全绿（含新增用例）。
- [ ] 服务端测试套件全绿（含新增用例）。

## 范围外

- `tag_session` / `delete_session`（后续 session 管理任务）
- Plan Mode 接完最后一公里（单独立项）
- 远程文件编辑回写（单独立项）
- `thinking` / `max_budget_usd` 透传（后续评估）
