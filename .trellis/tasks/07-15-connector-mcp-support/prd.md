# MCP 接入(内进程 + 外部 server)

## Goal

让连接器支持 MCP:注册内进程 MCP 工具、配置外部 MCP server、并暴露运行时状态查询。当前连接器完全不配 MCP —— `timeline_reducer.py` 的 `_tool_kind`/`_mcp_parts` 已能把 `mcp__server__tool` 命名的工具结果归类为 `kind:"mcp"` 并渲染,但 `_options_kwargs`(sdk_adapter.py:609)从不设置 `mcp_servers`,也从不注册任何 SDK 内工具,所以这条渲染路径永远不会被触发。

## 背景(调研已确认)

- SDK 0.2.116 提供:
  - 内进程 MCP:`create_sdk_mcp_server()` + `@tool` 装饰器 + `McpSdkServerConfig(type="sdk")`。
  - 外部 MCP:`ClaudeAgentOptions.mcp_servers`(dict / 路径),类型含 `McpStdioServerConfig` / `McpSSEServerConfig` / `McpHttpServerConfig`,以及 `strict_mcp_config`。
  - 运行时控制:`ClaudeSDKClient.get_mcp_status()`、`reconnect_mcp_server(name)`、`toggle_mcp_server(name, enabled)`。
  - 类型:`McpServerConfig/Status/ConnectionStatus/Info/StatusConfig`、`McpStatusResponse`、`McpToolAnnotations`、`McpToolInfo`。
- 本地 43 个 JSONL 历史中 **没有任何 MCP 调用**,说明这是纯新增能力,不影响存量数据回放。
- 下游渲染部分就绪:reducer 已产出 `kind:"mcp"` 含 `server`/`tool`/`arguments`/`result`/`error`,但需确认 web/Android 是否已有 mcp 卡片渲染(本任务需先核实,可能牵出客户端改动)。

## Requirements

- 连接器 `_options_kwargs` 支持从 start_turn params 或连接器配置注入 `mcp_servers`(至少覆盖 stdio 与 http/sse 两类外部 server)。
- 暴露 RPC 方法查询 MCP 状态(对齐 `get_mcp_status`),供客户端展示已连接 server 与其工具清单。
- 决定内进程 MCP(`@tool`)是否在本期范围内 —— 若纳入,给出注册点;若不纳入,在 Notes 标注为后续任务。
- 核实并(如缺失则补齐)客户端对 `kind:"mcp"` tool 卡片的渲染。
- MCP 配置涉及外部进程/网络端点,需遵循安全约定:凭证不落明文日志,server 配置来源可信。

## Acceptance Criteria

- [ ] 配置一个外部 MCP server(如 stdio 示例)后,其工具调用能在时间线正确显示为 `kind:"mcp"` 卡片(server/tool/参数/结果)。
- [ ] 有 RPC 能返回 MCP 连接状态与工具清单。
- [ ] 连接器 + 服务端测试通过,新增覆盖 MCP 配置注入与状态查询。
- [ ] 未配置 MCP 时行为与现状完全一致(无回归)。

## Notes

- 优先级 P3:纯增量能力,历史无 MCP 使用,非体验刚需。
- 内进程 MCP 与外部 MCP 可拆成两个子任务;若范围过大,先做外部 server 配置注入这一最小闭环。
- 关联梯队:第四梯队(高级特性)。
