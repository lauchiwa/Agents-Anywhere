# 接入 get_server_info 展示可用 slash commands 与 output styles

## Goal

SDK `client.get_server_info()` 在 connect 时已把 CLI 的 initialize 响应缓存在 `_initialization_result`，包含：
- `commands`: 可用 slash command 列表（含 name/description/isBuiltin/isEnabled 等字段）
- `output_style`: 当前输出格式字符串（如 "default"）

连接器目前完全没接入此 RPC，客户端无法得知 CLI 支持哪些 slash commands。

## Requirements

### 连接器
- 在 `claude/sdk_adapter.py` 加 `get_server_info(params)` 方法
  - 找到对应 session runtime，调 `runtime.client.get_server_info()`
  - session 不存在、client 未连接、SDK 不支持 → 返回 `{ok: false, reason: ...}`
  - 成功 → 返回 SDK 原始 dict（不做二次映射）
- 在 `connector/runtime.py` `handle_message` 加 `"runtime.getServerInfo"` 分派，转发给 sdk_adapter

### 服务端
- 无需改动（RPC 透传链路已覆盖）

### Web
- 在 session runtime settings sheet 里展示 slash commands 列表（如果 `get_server_info` 返回 commands 且非空）
- 展示条件：仅在有可用 commands 时显示，空则不显示该区块
- 调用时机：session 运行时 settings sheet 打开时懒加载（useQuery）

### Android
- 暂不实现（Compose 动态列表 + 实现成本，且 web 已覆盖；可后续补）

## Acceptance Criteria

- [ ] `runtime.getServerInfo` RPC 可通过 WebSocket 调用，返回 `{commands: [...], output_style: "..."}` 或降级 `{ok: false, reason: ...}`
- [ ] Web runtime settings sheet 展示 slash command 名+描述列表（有则显示，无则静默不显示区块）
- [ ] 连接器单元测试：有 client / 无 client / SDK 不支持三路径
- [ ] `connector pytest` + `web tsc` 全通

## Notes

- `get_server_info()` 的数据在 connect 时已缓存，调用成本极低（内存读）
- SDK 返回结构未在 TypedDict 中固定，按 docstring 约定：`commands` list + `output_style` str；实际字段直接透传，客户端按需读取
- Android 展示推后——web 先上，Android 另建子任务
