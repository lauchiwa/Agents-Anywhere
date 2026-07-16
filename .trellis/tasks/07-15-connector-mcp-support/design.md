# Design — MCP 外部 server 注入 + status RPC(A1 + B1)

## Scope

本迭代只做 **外部 MCP server（stdio/http/sse）** 的注入与状态查询,不含内进程 `@tool`,不含 UI 专属卡片(后者已拆到子任务 `07-16-connector-mcp-client-cards`)。

## Boundaries & Trust

- 配置来源:**连接器本地文件** `~/.agent-server/mcp.json`(与 `connector.json` 同目录,0600)。
  - 理由:MCP stdio 配置等价于"跑这条 shell 命令 + env",信任边界必须落在执行侧(连接器 = 用户设备)。服务端不下发 MCP server 配置,避免"服务端一旦被撑破,所有连接器同时 RCE"。
  - `strict_mcp_config=True` 一并置上,防止 CLI 从系统级配置源读取到本连接器未声明的 server。
- 与 `connector.json` 分离:身份凭证与 MCP 编排解耦,便于用户手动编辑 MCP 而不动 token,也便于以后独立轮换。

## Config File Contract(`mcp.json`)

```json
{
  "servers": {
    "docs": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-example"],
      "env": {"API_KEY": "..."}
    },
    "browser": {
      "type": "http",
      "url": "https://mcp.example.com/mcp",
      "headers": {"Authorization": "Bearer ..."}
    }
  }
}
```

- 顶层 key `servers` 固定,值为 `dict[server_name, McpServerConfig]`,字段与 SDK `McpStdioServerConfig / McpHttpServerConfig / McpSSEServerConfig` 完全对齐。
- `type` 缺省视为 `stdio`(SDK 已允许)。
- 文件不存在 = 无 MCP,与现状完全一致(无回归)。
- 加载失败(JSON 语法错 / schema 非法):记录错误,退回"无 MCP"而不是让 turn 起不来。

## Loader

新增 `connector/connector/claude/mcp_config.py`:

```python
@dataclass(slots=True)
class McpConfig:
    servers: dict[str, dict[str, Any]]

    @classmethod
    def default_path(cls) -> Path: ...      # env AGENT_CONNECTOR_MCP_CONFIG or ~/.agent-server/mcp.json
    @classmethod
    def load(cls, path: str | Path | None = None) -> "McpConfig": ...   # 缺文件 -> 空 dict
```

- `load()` 只做形状校验(顶层 `servers` 是 dict,每个 value 是 dict),字段级校验交给 SDK 自身。
- 保留敏感字段(`env`/`headers`)不进日志;记录只输出 `server_name` 与 `type`。

## Injection Point

`sdk_adapter.py:_options_kwargs`(现在的 `permission_mode/model/effort/max_turns` 之后):

```python
mcp_config = self._mcp_config_provider()   # 注入的 provider,方便测试
if mcp_config.servers:
    kwargs["mcp_servers"] = dict(mcp_config.servers)
    kwargs["strict_mcp_config"] = True
```

- `ClaudeSdkAdapter.__init__` 接受可选 `mcp_config_provider: Callable[[], McpConfig]`,缺省用 `McpConfig.load`。测试用 fake provider 注入内存配置。
- 每个 turn 重新读文件,让手动编辑 `mcp.json` 后无需重启连接器就生效。读文件失败退回上次成功值(或空)。

## Status RPC

新增 `mcp.status` 方法(顶层 `dispatch` 分派;handler 落在 `ClaudeSdkAdapter`):

- 契约:`params: {"sessionId": str}` 返回 `{"servers": [McpServerStatus, ...]}`(直接把 SDK `McpStatusResponse.mcpServers` 透传出去,不做字段重命名)。
- 实现:从 `_SdkSessionRuntime` 拿 `ClaudeSDKClient` 引用,`await client.get_mcp_status()`;若 session 未启动或 SDK 无该方法,返回 `{"servers": []}` 并附 `unavailable` 原因。
- 上层选择权在客户端:是否展示、如何刷新由 UI 决定;连接器只做"当前一次"查询。
- 后续需要"变化推送"再加,当前 SDK 也支持 `toggle_mcp_server/reconnect_mcp_server`,本迭代不做。

## Data Flow

```
mcp.json ── McpConfig.load ── provider ── _options_kwargs ── ClaudeAgentOptions.mcp_servers
                                                                          │
                                                                          ▼
                                                                CLI spawns MCP servers
                                                                          │
                                                                          ▼
                                                              tool events with name mcp__X__Y
                                                                          │
                                                                          ▼
                                                     timeline_reducer._mcp_parts → kind:"mcp"
                                                                          │
                                                                          ▼
                                                    client renders (generic tool fallback for now)

RPC mcp.status ── dispatch ── adapter.mcp_status(params) ── client.get_mcp_status() ── McpStatusResponse
```

## Compatibility & Rollback

- 无 `mcp.json`(默认状态):`_options_kwargs` 不塞 `mcp_servers` / `strict_mcp_config`,行为与今日完全一致 —— 这是零回归的保证。
- `strict_mcp_config=True` 仅在 servers 非空时置位,避免误关掉未来"SDK 默认预置 server"这类扩展。
- 回滚:删 `mcp.json` 或删两行 `_options_kwargs` 代码即回到 pre-MCP 状态,无 schema 迁移。

## Testing Strategy

- 连接器单测:
  - `McpConfig.load` 覆盖:缺文件、非法 JSON、非法 schema、正常 stdio、正常 http。
  - `_options_kwargs` 覆盖:空 config 不塞 mcp 字段、非空 config 塞入 `mcp_servers` + `strict_mcp_config=True`。
  - `mcp.status` handler:mock `client.get_mcp_status()` 返回,验证透传;session 未注册返回 `{"servers": []}`。
- 服务端:本任务不改服务端,不新增测试。
- E2E:留待有真实 MCP server 时手动验一次 stdio 例子(记录到 debug 回顾)。

## Out of Scope(follow-up)

- 内进程 `@tool` 注册(单开子任务)。
- `mcp.toggle` / `mcp.reconnect` RPC(现无用户场景)。
- 服务端下发 MCP 编排 + 本地 allowlist 混合模式(以后再说)。
- Web/Android MCP 专属卡片 → 子任务 `07-16-connector-mcp-client-cards`。

## Open Questions

- `mcp.status` 是不是应该纳入 `capabilities` 广播?倾向不:当前 capabilities 是"能力发现",MCP 状态更接近"运行时状态",按需查询即可。
