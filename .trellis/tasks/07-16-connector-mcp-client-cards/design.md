# Design: MCP 工具卡片渲染（Web + Android）

## 范围

Web 的 `session-tool-cards.tsx` 和 Android 的 `SessionDetailController.kt` / `SessionMessages.kt`，补齐 `kind:"mcp"` 的 arguments/result/error 详情展示。不新增后端契约，只消费 reducer 已产出的字段。

## Reducer 产出的字段（不可更改）

```ts
{
  kind: "mcp",
  server: string,          // MCP server name
  tool: string,            // tool name
  arguments: object,       // tool input
  result?: string,         // outputText when present
  outputText?: string,     // primary text result
  outputPreview?: string,  // truncated preview
  outputLength?: number,   // full length hint
  error?: string,          // error message string
  isError?: boolean,       // true when tool returned error
}
```

---

## Web 方案

### 现状

`ToolCard` → `ToolDetailPanel(command, output, changes, fallback)`：
- `output` 读 `outputPreview || outputText || error`（统一）
- MCP 命中 fallback → `<JsonBlock value={item.content} />`（把整个 content 对象 dump 出来，噪音多）

### 方案：在 `ToolDetailPanel` 里加 MCP 分支

在 `ToolCard` 中提取 `mcpProps`：

```tsx
const mcpArguments = item.content.kind === "mcp" ? item.content.arguments : null
const mcpError = item.content.kind === "mcp" ? textOf(item.content.error) : null
const mcpIsError = item.content.kind === "mcp" && Boolean(item.content.isError)
```

给 `ToolDetailPanel` 加三个可选 props：

```tsx
mcpArguments?: unknown   // object → JSON panel
mcpError?: string | null
mcpIsError?: boolean
```

内部渲染顺序（每节有内容才显示，用 border-t 分隔）：
1. `arguments` → `<CodePanel label="arguments" code={prettyJson} language="json" />` 
2. `output`（已有）→ `<CodePanel label="result" />` 
3. `mcpError` → `<CodePanel label="error" />` 带红色 label

`hasContent` 扩展：`|| mcpArguments != null || mcpError != null`

非 MCP 时三个 props 均为 null/undefined，现有路径零变化。

### label 样式

error label 用 `text-destructive` 区分成功/失败，无需改 `CodePanel` 签名，改 `CodePanelFrame` 的 `labelClassName` prop（可选，默认 `""`）。

---

## Android 方案

### 现状

MCP 分支只 `toToolCallMessage(title=tool, subtitle=server)`。`detail`/`body` 字段空，所以 `hasToolCallDetail = false`，展开区域不渲染。

### 字段映射

`TimelineMessage` 已有 `detail: String` 和 `body: String`，被 `CommandPreview` / `DiffPreview` 使用。MCP 复用同一机制：

```kotlin
// SessionDetailController.kt
"mcp" -> listOf(
    toToolCallMessage(
        title  = content.text("tool") ?: "tool",
        subtitle = content.text("server") ?: "mcp",
        detail = prettyJson(content.json("arguments")),  // arguments JSON
        body   = content.text("outputText") ?: content.text("result") ?: "",
        // error folded into body when isError
    )
)
```

`hasToolCallDetail` 因 `detail.isNotBlank()` 变 true，展开区域自动显示。

### 渲染路径

`ToolActivityCard` → 展开区 → `when(message.kind)` → 目前 MCP 走 else（只显示 subtitle）。新增 MCP 专属 section：

```kotlin
TimelineMessageKind.ToolCall && message.title != "" && message.detail.isNotBlank() ->
    McpToolPreview(arguments = message.detail, output = message.body, isError = message.body.startsWith("Error:"), darkMode)
```

实际上更干净的做法：在 `ToolActivityCard` 展开内容里，当 `message.kind == ToolCall && message.detail.isNotBlank()` 时直接走 `McpToolPreview`（复用 `CommandPreviewSection` 的样式）。

`isError` 通过 controller 在 `toToolCallMessage` 时以 `"Error: $error"` 前缀 folding 进 body，或直接新增 boolean 字段。选**前缀方案**：不改 `TimelineMessage` 签名，`McpToolPreview` 通过 `body.startsWith("Error:")` 区分。

### McpToolPreview composable

```kotlin
@Composable
private fun McpToolPreview(arguments: String, output: String, isError: Boolean, darkMode: Boolean) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (arguments.isNotBlank()) {
            CommandPreviewSection(label = "arguments", text = arguments, languageHint = "json", darkMode = darkMode)
        }
        if (output.isNotBlank()) {
            CommandPreviewSection(
                label = if (isError) "error" else "result",
                text = if (isError) output.removePrefix("Error: ") else output,
                languageHint = null,
                darkMode = darkMode,
            )
        }
    }
}
```

`CommandPreviewSection` 已存在（`SessionMessages.kt` 中），直接复用，不新建组件系统。

---

## 兼容性

- 旧 MCP 项（`arguments` / `outputText` 可能为 null）：空字符串 fallback，不崩溃。
- 非 MCP 工具：代码路径完全不变。
- Web fallback：当 `mcpArguments` 为 null 且 `hasContent` 为 false 时仍走 `<JsonBlock>`。
