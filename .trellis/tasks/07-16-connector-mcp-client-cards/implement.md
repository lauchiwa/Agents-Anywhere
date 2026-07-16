# Implement: MCP 工具卡片渲染

## 前置条件

Active task: `.trellis/tasks/07-16-connector-mcp-client-cards`

## 步骤

### Step 1 — Web: 给 `ToolDetailPanel` 加 MCP props

文件：`web-next/src/components/session/session-tool-cards.tsx`

1.1 给 `ToolDetailPanel` 的 props 类型增加三个可选字段：
```ts
mcpArguments?: unknown
mcpError?: string | null
mcpIsError?: boolean
```

1.2 扩展 `hasContent` 判断：
```ts
const hasContent = Boolean(command || output || changes.length > 0 || mcpArguments != null || mcpError != null)
```

1.3 在 render 里 `output` section 之前插入 arguments section：
```tsx
{mcpArguments != null ? (
  <div className={cn((command || changes.length > 0) && "border-t")}>
    <CodePanel label="arguments" code={JSON.stringify(mcpArguments, null, 2)} language="json" flush />
  </div>
) : null}
```

1.4 把现有 `output` section 的 label 根据 `mcpIsError` 切换：
- 非 MCP：label 保持 `"output"`（不变）
- MCP：label 改为 `mcpIsError ? "error" : "result"`
- 实现方式：在 ToolCard 调用层传 `outputLabel?: string` 或直接在 ToolDetailPanel 内判断（优先后者，避免改调用层）

  在 ToolDetailPanel 内部：
  ```tsx
  const outputLabel = mcpIsError ? "error" : mcpArguments != null ? "result" : "output"
  ```

1.5 在 `<CodePanel label={outputLabel} ... />` 中，当 `mcpIsError` 时给 label 加红色：
  给 `CodePanelFrame` 加可选 `labelClassName?: string`，在 `CodePanel` 内透传；当 `mcpIsError` 时传 `"text-destructive"`。

1.6 在 `ToolCard` 里计算并传入 MCP props：
```tsx
const isMcp = timelineToolKind(item) === "mcp"
const mcpArguments = isMcp ? item.content.arguments ?? null : null
const mcpErrorText = isMcp ? (textOf(item.content.error) ?? null) : null
const mcpIsError = isMcp && Boolean(item.content.isError)
// 当 isError 时把 error 合并进 output（或在 ToolDetailPanel 中处理）
const output = textOf(item.content.outputPreview) || textOf(item.content.outputText) || (!isMcp ? textOf(item.content.error) : null)
```

将 `mcpArguments`, `mcpError`, `mcpIsError` 传给 `ToolDetailPanel`。

### Step 2 — Android: 填充 controller 的 MCP detail/body

文件：`android/app/src/main/java/com/agentsanywhere/app/feature/sessiondetail/SessionDetailController.kt`

找到 `"mcp" ->` 分支（约 657 行），替换为：

```kotlin
"mcp" -> {
    val args = content.json("arguments")
    val argsJson = if (args != null) prettyJson(args) else ""
    val outputText = content.text("outputText") ?: content.text("result") ?: ""
    val errorText = content.text("error") ?: ""
    val isError = content.boolean("isError") == true || errorText.isNotBlank()
    val body = when {
        isError && errorText.isNotBlank() -> "Error: $errorText"
        outputText.isNotBlank() -> outputText
        else -> ""
    }
    listOf(
        toToolCallMessage(
            title = content.text("tool") ?: "tool",
            subtitle = content.text("server") ?: "mcp",
            detail = argsJson,
            body = body,
        )
    )
}
```

需要确认：
- `content.json("arguments")` 是否已有 helper 方法，或需要用 `content.obj("arguments")` / `content.jsonObject("arguments")`。查看现有 helper 后选对应方法。
- `prettyJson()` 是否已有工具函数（在项目中 grep `prettyJson` 或 `JsonObject`）；若无，用 `Json.encodeToString(content.json("arguments")!!)` 或 `arguments.toString()` 作为 fallback。

### Step 3 — Android: 新增 McpToolPreview composable

文件：`android/app/src/main/java/com/agentsanywhere/app/ui/screens/sessiondetail/SessionMessages.kt`

3.1 新增 composable（放在 `CommandPreview` 之后）：

```kotlin
@Composable
private fun McpToolPreview(arguments: String, output: String, isError: Boolean, darkMode: Boolean) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (arguments.isNotBlank()) {
            CommandPreviewSection(
                label = stringResource(R.string.session_mcp_arguments),
                text = arguments,
                languageHint = "json",
                darkMode = darkMode,
            )
        }
        if (output.isNotBlank()) {
            val cleanOutput = if (isError) output.removePrefix("Error: ") else output
            CommandPreviewSection(
                label = if (isError) stringResource(R.string.session_mcp_error) else stringResource(R.string.session_mcp_result),
                text = cleanOutput,
                languageHint = null,
                darkMode = darkMode,
            )
        }
    }
}
```

3.2 在展开区域（`hasToolCallDetail` 为 true 时）插入 MCP 分支：

找到展开内容区（约 1405–1450 行），在 `message.kind == TimelineMessageKind.ToolCall` 的 else/when 内加：

```kotlin
message.kind == TimelineMessageKind.ToolCall && message.detail.isNotBlank() ->
    McpToolPreview(
        arguments = message.detail,
        output = message.body,
        isError = message.body.startsWith("Error:"),
        darkMode = darkMode,
    )
```

⚠️ 注意：当前 `else ->` 分支只显示 `subtitle`。新增 MCP 分支后，未填 `detail` 的 ToolCall（如 web_search、schedule_wakeup）仍走原 `else`，不受影响。

3.3 String resources（`strings.xml`）：
新增三个 string：
```xml
<string name="session_mcp_arguments">arguments</string>
<string name="session_mcp_result">result</string>
<string name="session_mcp_error">error</string>
```

若项目用硬编码英文 strings 而非 res，则直接写字符串字面量，无需改 strings.xml。

### Step 4 — 验证命令

Web：
```bash
cd web-next && pnpm typecheck 2>&1 | tail -20
```

Android：
```bash
cd android && ./gradlew :app:compileDebugKotlin 2>&1 | tail -30
```

若类型/编译无误则通过，无需运行完整测试套件（UI 变更靠手动/截图验证）。

## 关键约束

- 不改 reducer payload 字段命名
- `ToolDetailPanel` 非 MCP 调用路径零变化（mcpArguments=null 时 hasContent 逻辑与现在等价）
- Android 不新增 TimelineMessage 字段，用已有 detail/body
- `CommandPreviewSection` 直接复用，不新建 UI 组件系统
