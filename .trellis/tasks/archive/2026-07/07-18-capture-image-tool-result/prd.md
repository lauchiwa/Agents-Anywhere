# PRD: Connector 捕获 image tool_result 数据结构

## Background

`07-15-connector-render-output-images` 的实现被阻塞：不知道 SDK 实际返回的
`image` tool_result block 的字段结构（base64? URL? content type 如何传递？）。
需要在 connector 里加 debug 日志，让下次自然触发图片工具调用时自动把原始结构持久化，
供后续实现参考。

## Goals

- 在 connector 的 tool_result 处理路径中，若 block type 为 `image`，将原始 block
  结构 dump 到 connector 日志（WARNING 级别，确保默认可见）
- 日志内容足够完整（JSON 序列化），可直接用于 `07-15` 的实现

## Non-Goals

- 实现图片渲染（那是 `07-15` 的工作）
- 修改任何对外行为（纯观察性日志，不影响现有流程）

## Acceptance Criteria

1. 在 `sdk_adapter.py` 的 tool_result / content block 处理路径中，找到 image block
   的分支（或添加一个 fallthrough 日志），当 `block_type == "image"` 时记录：
   - block 的全部字段（用 `json.dumps` 或 `repr`）
   - 来源 session_id / turn_id
2. 日志级别 WARNING（保证在生产日志中可见）
3. 不破坏现有测试（connector pytest 全通过）
4. TypeScript 无需变更

## Key Files

- `connector/connector/claude/sdk_adapter.py` — tool_result / block 处理路径
