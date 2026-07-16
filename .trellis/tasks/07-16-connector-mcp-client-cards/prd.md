# 客户端 MCP 工具卡片渲染(web/Android)

## Goal

补齐 web/Android 对 `kind:"mcp"` 时间线项的专属渲染,展示 server/tool/arguments/result/error。父任务 [[07-15-connector-mcp-support]] 走通端到端配置注入后由本任务打磨 UI。

## 现状(2026-07-16 调研)

- 连接器 reducer 已产出干净 payload(`timeline_reducer.py:344-379`):`{toolUseId, toolName, input, kind:"mcp", server, tool, arguments, result?, error?, isError?, text?, outputText?, outputPreview?, outputLength?}`。
- **Web**(`web-next/src/components/session-tool-cards.tsx:31,122-125,163`):无 MCP 专属卡。`timelineToolTitle` 只用 `<server> / <tool>` 拼标题,`arguments/result/error` 全落到通用 `ToolDetailPanel` 的 JSON dump。
- **Android**(`android/.../SessionDetailController.kt:652,657-662`):无 MCP 专属卡。`title=tool`、`subtitle=server` 就完事,`arguments/result/error` 完全没渲染 —— 用户点开一个 MCP 工具**只能看到名字**。

## Requirements

- Web:新增或扩展渲染分支,把 arguments/result/error 展开为可读结构(JSON 折叠 + 错误高亮),不再依赖 fallback JSON dump。
- Android:新增 MCP 专属 composable 或复用现有 tool card 的可展开区,渲染 arguments/result/error;错误态视觉可区分。
- 保持与 reducer 产出的字段命名一致(`server/tool/arguments/result/error/isError/outputText/outputPreview/outputLength`),不新增契约。
- 无 MCP 时不受影响(未配置或历史无 MCP 数据回归零变化)。

## Acceptance Criteria

- [ ] Web:点开一个 MCP 工具项,能看到 server、tool、arguments(JSON)、result 文本/预览、error(若有)。
- [ ] Android:同上;错误态在视觉上区别于成功。
- [ ] Web/Android 使用父任务落地的真实 MCP 数据做至少一次端到端渲染验证(截图或本地演示)。
- [ ] 现有非 MCP 工具卡片行为无变化。

## Notes

- 优先级 P3,依赖父任务 [[07-15-connector-mcp-support]] 提供真实 MCP 数据。
- 父任务 done 之前可先起草设计,但集成验证需等父任务能配置出可用 MCP server。
- 关联梯队:第四梯队(高级特性)UI 打磨。
