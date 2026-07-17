# implement.md — runtime 控制增强：1M betas 修复 + auto 模式 + stop_task

## 关键文件定位

| 文件 | 相关位置 |
|------|----------|
| `connector/connector/claude/sdk_adapter.py` | `_options_kwargs` L974；model 透传 L996；`set_permission_mode` L259；新增 `stop_task` |
| `connector/connector/runtime.py` | RPC 分派 L327-；新增 `task.stop` 分支 |
| `server/agent_server/core/runtime_config.py` | Claude permissionMode schema L99-108 |
| `server/agent_server/api/connector_ingress.py` | RPC 下发入口；新增 `task.stop` |
| `web-next/src/` | permissionMode 选项文案；子代理进度卡停止按钮 |
| `connector/tests/` | 新增三个测试用例 |
| `server/tests/` | permissionMode 透传测试 |

---

## 执行清单

### Item 1：`[1M]` model 后缀 → betas 注入（Bug Fix）

- [ ] **1.1** `sdk_adapter.py` 在 `_options_kwargs`（L996 附近）的 model 处理处：
  - 检测 `model.endswith("[1M]")`
  - 剥离后缀：`real_model = model.removesuffix("[1M]")`
  - 注入 `kwargs["betas"] = ["context-1m-2025-08-07"]`
  - 最终 `kwargs["model"] = real_model`
  - 非 `[1M]` 型号走原有逻辑不变

- [ ] **1.2** 连接器测试：`test_1m_model_suffix_strips_suffix_and_injects_betas`
  - `[1M]` 型号 → options 含 `betas=["context-1m-2025-08-07"]`，`model` 无后缀
  - 普通型号 → options 无 `betas` 键

### Item 2：`auto` / `dontAsk` 权限模式暴露

- [ ] **2.1** `server/agent_server/core/runtime_config.py` L103-108，在 Claude permissionMode 选项列表末尾追加：
  ```python
  RuntimeConfigOption(value="auto", label="Auto mode", description="Model classifier auto-approves safe tool calls"),
  RuntimeConfigOption(value="dontAsk", label="Don't ask", description="Reject all unapproved tools without prompting"),
  ```

- [ ] **2.2** i18n — `web-next/` 和 Android `strings.xml`（en + zh）补充 `auto`/`dontAsk` 的描述文案（若客户端有权限模式说明文本的话）。若只是 label 字符串，直接在 schema 里写英文即可，不需要单独 i18n key。

- [ ] **2.3** 验证：`set_permission_mode("auto")` 和 `set_permission_mode("dontAsk")` 已能透传（`sdk_adapter.py:259`，现有逻辑已支持），无需改连接器。

- [ ] **2.4** 服务端测试：`test_permission_mode_auto_and_dontask_in_schema`
  - runtime_config 的 claude permissionMode 选项包含 `auto` 和 `dontAsk`

### Item 3：`stop_task` RPC 全链

- [ ] **3.1** `sdk_adapter.py`：在 `_SdkSessionRuntime` 或 `ClaudeSdkAdapter` 上新增 `stop_task(task_id: str)` 方法：
  ```python
  async def stop_task(self, task_id: str) -> dict:
      if self._client is None:
          return {"ok": False, "reason": "no active session"}
      await self._client.stop_task(task_id)
      return {"ok": True}
  ```

- [ ] **3.2** `runtime.py`：在 RPC 分派链（L327-）加：
  ```python
  if method == "task.stop":
      return await self._adapter.stop_task_for_session(
          params.get("sessionId"), params.get("taskId")
      )
  ```
  `stop_task_for_session` 内部经 `_runtime_for(session_id)` 找到对应 runtime，再调其 `stop_task`。无 active client 时返回降级。

- [ ] **3.3** `server/agent_server/api/connector_ingress.py`：加 `task.stop` 下发入口（参照现有 `turn.interrupt` 下发模式）。服务端新增 API 端点 `POST /api/sessions/{session_id}/task/stop`，body `{taskId: str}`，内部调 connector RPC `task.stop`。

- [ ] **3.4** Web（`web-next/src/`）：在子代理进度卡（`SubagentProgressBadge` 或 `session-timeline-entry.tsx`）上，对 `status=running` 的子代理显示"停止"按钮，点击调服务端新 API。

- [ ] **3.5** 连接器测试：`test_stop_task_rpc_calls_client_stop_task` + `test_stop_task_no_active_client_returns_degraded`

---

## 验证命令

```bash
# 连接器测试
cd connector && uv run pytest tests/ -x -q 2>&1 | tail -5

# 服务端测试
cd server && uv run pytest tests/ -x -q 2>&1 | tail -5

# Web 类型检查
cd web-next && yarn tsc --noEmit 2>&1 | tail -5
```

## 注意事项

- Item 1 和 Item 2 独立于 Item 3，可并行实现
- `stop_task` 服务端 API 端点参照 `connector_ingress.py` 里 `interrupt_session` 的下发模式，不要重复造轮子
- Web 停止按钮只对 `status=running` 的子代理显示，已完成/失败的不显示
- Android 子代理卡的停止按钮可作为后续任务（当前 Android 编辑类工作易出幻觉问题）
