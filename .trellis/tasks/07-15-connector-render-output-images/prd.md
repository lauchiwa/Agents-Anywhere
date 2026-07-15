# 连接器渲染 tool_result 内嵌的图片块

## Goal

部分工具（截图类工具、某些 MCP 工具）的 `tool_result` 里可能内嵌 `image` content block，当前 `_tool_result_content` / `_blocks_to_dicts` 不解析它，用户看不到工具返回的图片。范围收窄为**只处理 tool_result 内嵌 image**，不再追求"渲染模型输出的图片"。

## 实测背景（2026-07-15，改变了任务定性）

动手前抓了本地全部相关 JSONL 实测，结论推翻了原 prd 的假设：

- 原 prd 称"12 个 assistant 输出 image + 1 个 tool_result 内嵌 image"。
- 实际只有 **3 个 image block，全部在 `user` 消息里**（用户上传图片的回显，非模型生成）。
- **0 个** assistant 输出 image，**0 个** tool_result 内嵌 image。

结论：当前 Claude 模型不生成 image content block（文生图不是其能力），"渲染模型输出图片"在真实数据里无实例支撑。唯一现实的图片来源是**工具返回内嵌 image**（截图/部分 MCP 工具），但本地尚无实例——属于未来可能出现、当前无法验证的能力。

据此该任务已**降级 P1 → P3**、范围收窄为 tool_result image。

## 现状

- `_blocks_to_dicts`（sdk_adapter.py）只处理 text/tool_use/tool_result/thinking，无 image 分支。
- `_tool_result_content`（normalizers.py）把 tool_result 的 content 当作纯文本抽取（`_result_text`），内嵌 image 会被丢弃或降级成文本。
- 输入侧图片已支持：`_materialize_runtime_content` 会封装 base64 image 块喂给模型。
- 时间线 content 落库在 `timeline_items.payload_json`（Text 列），SSE 每次全量推送——**大 base64 内联进 content 会拖垮实时推送**，需评估落盘 + 走既有 fs transfer 下载通道（`connector_fs_transfer_upload`）而非内联。

## Requirements

- 先决：抓到一次真实的 tool_result 内嵌 image 实例（本地复现或生产日志），确认真实结构后再动手——本地当前 0 例，不要凭空实现。
- `tool_result` 的 content 数组解析支持 image 子块（`{"type":"image","source":{...}}`）。
- 图片字节不内联进时间线 content：落盘 + 通过既有附件/fs transfer 通道供客户端按需下载，时间线里只存引用。
- 归一化 + reduce 打通，实时与历史同源。
- 确认三层客户端渲染（web `ArtifactCard` / Android 对应卡片是否已支持图片；见下游调查结论）。

## Acceptance Criteria

- [ ] 有真实 tool_result image 实例作为测试与验证依据（无实例则本任务保持 planning，不实现）。
- [ ] tool_result 内嵌 image 被解析成可渲染的时间线项，字节走下载通道而非内联。
- [ ] 历史回放路径同源生效。
- [ ] 新增 parity 测试覆盖。
- [ ] 连接器完整测试套件全绿。
- [ ] 三层客户端能渲染（不足则补齐）。

## Notes

- 优先级 **P3**（现实数据无实例，价值不确定，等真实场景出现再做）。
- 不含"模型直接输出 image"——Claude 不具备该能力，已从任务范围剔除。
