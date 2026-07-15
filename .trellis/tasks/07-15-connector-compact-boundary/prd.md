# compact 压缩边界感知

## Goal

本地历史里有 `system/subtype=compact_boundary`（8 次，带完整 `compactMetadata`：trigger / preTokens / postTokens / cumulativeDroppedTokens / durationMs / preservedSegment）。连接器不识别这类记录，压缩发生时客户端时间线会“莫名跳变”——大段历史消失但无任何解释。

## Background（调研结论）

- 记录形态：`{"type":"system","subtype":"compact_boundary","compactMetadata":{...}}`；另有 `isCompactSummary=true` 标记与 attachment `compact_file_reference`。
- 实时侧 `_receive_response` 的 system 分支直接跳过；历史侧 normalizer 也无 compact 分支。
- 下游无现成 UI，需要新增一个"上下文已压缩"的分隔/提示项。

## Requirements

- normalizer（历史）+ `_receive_response`（实时，若 SDK 以消息形式 emit）识别 compact_boundary。
- 产出一个轻量系统时间线项（如 `content.kind == "compact"`），携带 trigger 与前后 token 数。
- 客户端渲染为一条不可展开的分隔提示（"上下文已压缩：N → M tokens"）。
- 不破坏 `preservedSegment` 之后的正常消息顺序。

## Acceptance Criteria

- [ ] compact_boundary 在历史回放中被识别并产出系统项。
- [ ] 客户端显示压缩发生的分隔提示与 token 变化。
- [ ] 压缩点前后的时间线顺序正确，无重复或错位。
- [ ] 连接器 parity 测试覆盖 compact_boundary（实时/历史一致）。

## Notes

- 优先级 P2。
- 与 context-token-usage 相关（同属上下文可观测性），但可独立完成。
