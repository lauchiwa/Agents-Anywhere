# Implement — MCP 外部 server 注入 + status RPC

按顺序执行,每一步单独可测,遇到问题可停在任意步骤回滚。

## Step 1 — McpConfig loader

- [ ] 新增 `connector/connector/claude/mcp_config.py`
  - `@dataclass McpConfig(servers: dict[str, dict[str, Any]])`
  - `default_path()`:`env AGENT_CONNECTOR_MCP_CONFIG` 优先,否则 `~/.agent-server/mcp.json`
  - `load(path=None)`:缺文件返回空 config;JSON 解析或形状校验失败返回空 config,同时用 `logging` 打警告(不含 env/headers)
- [ ] 新增 `connector/tests/test_mcp_config.py`
  - 缺文件 -> 空 servers
  - 合法 stdio + http 混合 -> 字段完整读入
  - 非法 JSON / 顶层不是 `{"servers": {...}}` -> 空 servers + warning

**Validate:** `cd connector && uv run pytest tests/test_mcp_config.py -q`

## Step 2 — Adapter provider hookup

- [ ] `ClaudeSdkAdapter.__init__` 增可选 `mcp_config_provider: Callable[[], McpConfig] | None = None`
  - 缺省 provider = `lambda: McpConfig.load()`
- [ ] `_options_kwargs`:在 `max_turns` 之后追加
  ```python
  mcp_config = self._mcp_config_provider()
  if mcp_config.servers:
      kwargs["mcp_servers"] = dict(mcp_config.servers)
      kwargs["strict_mcp_config"] = True
  ```
- [ ] `runtime.py` 里构造 `ClaudeSdkAdapter` 处不动(用默认 provider),确保生产路径零改动。

**Validate:** `cd connector && uv run pytest tests/test_claude_sdk_adapter.py -q`(现有测试全绿)

## Step 3 — Adapter tests for injection

- [ ] 在 `test_claude_sdk_adapter.py` 加两个用例:
  - 空 provider -> `options.kwargs` 里不含 `mcp_servers` / `strict_mcp_config`(现状回归)
  - 非空 provider -> `options.kwargs["mcp_servers"]` 与传入一致,`strict_mcp_config` 为 `True`
- 用注入的 fake provider,不碰真实文件系统。

**Validate:** `cd connector && uv run pytest tests/test_claude_sdk_adapter.py -q`

## Step 4 — mcp.status RPC handler

- [ ] `ClaudeSdkAdapter` 新增 `async def mcp_status(self, params: dict) -> dict`
  - 校验 `sessionId`
  - 从 `_runtimes` 拿 runtime;无对应或未连接返回 `{"servers": [], "unavailable": "session_not_active"}`
  - `client = runtime.client`;若 `getattr(client, "get_mcp_status", None)` 为 None 返回 `{"servers": [], "unavailable": "sdk_unsupported"}`
  - `resp = await client.get_mcp_status()`,返回 `{"servers": resp.get("mcpServers", [])}`
- [ ] `runtime.py:dispatch` 加分支:
  ```python
  if method == "mcp.status":
      adapter = self._require_adapter(params, default="claude")
      return await adapter.mcp_status(params)
  ```
  (沿用现有 `runtime.setModel` 那一带的模式:方法名 → adapter 属性)

**Validate:** 补 `test_claude_sdk_adapter.py::test_mcp_status_*` 三例:
- session 未注册 -> `unavailable=session_not_active`
- SDK client 无该方法 -> `unavailable=sdk_unsupported`
- mock `get_mcp_status` -> 透传 servers 数组

## Step 5 — Full connector suite

- [ ] `cd connector && uv run pytest -q`
- [ ] 无回归。

## Step 6 — Manual smoke(optional,依赖真实 MCP)

- 写一份最简 `mcp.json` 挂 `@modelcontextprotocol/server-example`(或任一真机可用 MCP)
- 启一个 turn,让模型调用该 server 的一个工具
- 观察时间线 item 是否落成 `kind:"mcp"`;记录一段调用链到任务的 debug 笔记

若本地没有真机 MCP 环境,跳过此步并在 PR 描述中说明。

## Step 7 — Update spec + commit + finish

- [ ] `trellis-update-spec`:把 `mcp.json` 契约与 `mcp.status` RPC 补到 connector 的 spec index。
- [ ] Commit(建议单笔):`feat(claude): inject mcp_servers from local config and expose mcp.status RPC`
- [ ] `/trellis:finish-work`。

## Rollback Points

- Step 1/2/3 独立:任何一步失败可只回退当前步骤,不影响其他。
- Step 4 依赖 Step 2 已合入 provider hook,不建议单独跳过。
- 已发布后回滚:删 `~/.agent-server/mcp.json` 即恢复"无 MCP",无 schema/DB 迁移需要撤。
