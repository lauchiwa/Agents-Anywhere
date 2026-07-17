# PRD: 全面项目审计

## Background

本次审计是在最近一系列功能开发（MCP支持、resilience修复、i18n修复、子代理进度、session管理等）之后，对整个项目进行系统性质量检查，目的是发现代码层面的正确性缺陷、安全风险、状态一致性问题，以及架构层面的潜在隐患。

## Scope

三端全量审计：
1. **Server** (`server/agent_server/`) — FastAPI + SQLAlchemy async
2. **Connector** (`connector/connector/`) — Python bridge to Claude CLI/SDK
3. **Web frontend** (`client/web/`) — Next.js/React
4. **Android client** (`client/android/`) — Kotlin/Compose

## Audit Dimensions

### 1. 正确性 (Correctness)
- 逻辑 bug：边界条件、None 守卫、错误分支遗漏
- 状态机一致性：session status 转换、active run 生命周期
- 并发安全：async race condition、数据库事务边界
- 数据完整性：外键关系、孤儿记录、JSON blob 解析守卫

### 2. 安全性 (Security)
- 认证/授权：所有 API 端点是否正确验证所有权（userId 检查）
- 注入风险：SQL、命令行、路径遍历
- 信息泄露：敏感字段是否出现在日志、错误响应中
- IDOR（越权访问）：资源 ID 是否存在跨用户访问漏洞

### 3. 弹性 (Resilience)
- 错误隔离：单点失败是否会级联崩溃
- 超时与重试：RPC 调用是否有合理超时
- 资源泄漏：连接、文件句柄、Future 是否在所有路径上释放

### 4. 状态一致性 (State Consistency)
- 服务端与连接端状态是否同步
- 数据库中的 JSON blob 与 Pydantic 模型是否一致
- MCP 配置合并逻辑的边界行为

### 5. 测试覆盖缺口 (Test Coverage Gaps)
- 关键路径是否有对应测试
- 现有测试是否覆盖异常路径

## Acceptance Criteria

- [ ] 对每个审计维度输出发现列表（Severity: P0/P1/P2/P3）
- [ ] P0/P1 问题必须在本任务内修复并提交
- [ ] P2/P3 问题记录到本文档末尾备忘
- [ ] 审计完成后所有现有测试仍然通过（server 218+，connector 187+）
- [ ] 所有修复通过 trellis-check 验证

## Out of Scope

- 新功能开发
- 性能优化（除非发现明显 O(n²) 类问题）
- 基础设施/部署配置（属于 qiwa-deploy 仓库范畴）
- `07-15-connector-render-output-images`（待真实数据，维持阻塞）

## Notes

- 参考最近已修复的 8 个 bug（Session 5 审计），避免重复
- env/headers 明文存储是设计决策，不计入安全缺陷
- MCP `sdk` 类型拒绝是设计决策

## P2/P3 Backlog（审计中补充）

### Server

**P3** `server/agent_server/api/connector_ingress.py:499`
— `params["sessionId"]` / `params["item"]` 在 `apply_connector_notification` 中无键守卫。坏帧已被批量隔离（15e6730），不会崩溃，但日志区分度差（"bad notification" 而非 "malformed frame"）。可选：加 `.get()` + 更清晰日志。

**P3** `server/agent_server/api/sessions.py:452,467`
— `enable/disable_takeover` 先 `get_session(user_id)` 再 `set_takeover(session_id)` 无 user_id 参数，所有权已由前者验证，安全但与 `rename_session` 不一致。防御纵深：`set_takeover` 可接受 user_id 参数。

**P3** `server/agent_server/api/connectors.py:597`（fs transfer download）
— 已分析：不是 IDOR。`_require_owned_online_connector` + `transfer.connector_id == connector_id` 双重守卫，token secrets-based 不可猜。补一个跨用户回归测试来文档化此边界。

**P3** Test coverage gap
— `send_message` 缺少"attachment 失败时 session 不卡在 running"的回归测试（P1 修复的 session_run.py:232 fix 对应）。

### Connector

**P2** `connector/connector/claude/sdk_adapter.py:1086-1094` — `_runtime_from_context` 错误会话兜底
— 当 `context.session_id` 缺失时，返回第一个有 `active_turn_id` 的 runtime。两个会话并发跑 turn 时，approval 可能绑到错误会话。当前 SDK 总会提供 `context.session_id`，兜底路径基本不触发，但属结构性风险。根本修复需要 SDK 端每次调用提供可靠的 session anchor，目前不具备条件。待 SDK 升级后再处理。

**P3** `connector/connector/claude/sdk_adapter.py:1308-1318` — `_disconnect_client` 注释与代码不符
— 注释称"先 disconnect 再 close"，但 loop 在找到第一个可调用方法后即返回；若 disconnect() 抛异常，close() 不执行。Best-effort teardown，可接受，留存。

**P3** `connector/connector/claude/sdk_adapter.py:504-608` — 缓冲消息排序边界
— pre-session_id 消息在 result/no-result 分支才 flush，第一条 mid-stream 消息揭示 session_id 后不立即 flush；缓冲消息可能比后续实时消息 orderSeq 更高。极低概率（首条 stream event 通常带 session_id），留存。

**P3** `connector/connector/runtime.py:886-888` — terminal relay token 在 URL query string
— connector → server 走 wss，token 短期有效，风险低。Header auth 更干净，可能是已知权衡。留存。

**P3** Test gap — shell-task 取消测试未断言无 "completed" 通知
— `test_connector_runtime.py:1299` 只验证最后一条通知是 "cancelled"，未验证期间没有 "completed"；P2 竞态修复缺对应回归测试。时序依赖测试难写，留存。

### Frontend (Web + Android)

**P3** `web-next/src/lib/dashboard/api.ts:253,257` + `android/…/SessionsApi.kt:174`
— Auth token 通过 SSE URL query string 传递（EventSource 无法设 header 的标准做法），但 token 会出现在访问日志。
— 未来缓解方向：短期 stream ticket 替代 token。

**P3** `web-next/src/lib/attachment-cache.ts:61`
— object URL 缓存在 module-level Map 中，从不调用 `URL.revokeObjectURL()`。慢速有界泄漏，不崩溃。

**P3** `web-next/src/components/workspace-context.tsx:546,560`
— `togglePinSession` / `toggleArchiveSession` 乐观更新后 await patch 但无 catch；失败时 UI 状态卡在错误值 + unhandled rejection。同文件 `renameSession`（line 574）有正确 rollback 示范，pin/archive 应对齐。
