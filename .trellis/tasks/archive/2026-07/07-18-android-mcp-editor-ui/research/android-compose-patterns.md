# Research: Android Compose Patterns for Dynamic Lists and Text Input

- **Query**: Existing Compose patterns for add/remove rows, key-value pairs, text inputs in Android
- **Scope**: internal
- **Date**: 2026-07-18

## Findings

### Files Found

| File Path | Description |
|---|---|
| `android/app/src/main/java/com/agentsanywhere/app/ui/screens/devices/DeviceAgentSettingsSheet.kt` | `NumberSettingRow` — OutlinedTextField example |
| `android/app/src/main/java/com/agentsanywhere/app/ui/screens/devices/DeviceSetupSheet.kt` | `BasicTextField` with custom styling |
| `android/app/src/main/java/com/agentsanywhere/app/ui/screens/devices/DeviceActionsSheet.kt` | `BasicTextField` with FocusRequester, rename flow |

### OutlinedTextField Pattern (DeviceAgentSettingsSheet.kt:549-579)

`NumberSettingRow` uses `OutlinedTextField` directly:
```kotlin
OutlinedTextField(
    value = text,
    onValueChange = { raw -> ... },
    enabled = enabled,
    singleLine = true,
    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
    placeholder = { Text(field.description ?: field.label, color = palette.secondaryText) },
    modifier = Modifier.fillMaxWidth(),
)
```

### BasicTextField Pattern (DeviceSetupSheet.kt:5-6, DeviceActionsSheet.kt)

Both sheets use `BasicTextField` with `SolidColor` cursor and custom decoration box. Pattern:
```kotlin
BasicTextField(
    value = text,
    onValueChange = { text = it },
    singleLine = true,
    textStyle = TextStyle(color = ..., fontSize = 14.sp),
    cursorBrush = SolidColor(color),
    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words, imeAction = ImeAction.Done),
    keyboardActions = KeyboardActions(onDone = { ... }),
    modifier = Modifier.fillMaxWidth().focusRequester(focusRequester),
    decorationBox = { innerTextField -> Box(...) { innerTextField() } }
)
```

With `LaunchedEffect(Unit) { focusRequester.requestFocus() }` for auto-focus.

### Scrollable Column Pattern

All sheets use:
```kotlin
Column(
    modifier = Modifier
        .heightIn(max = bodyMaxHeight)
        .fillMaxWidth()
        .verticalScroll(rememberScrollState()),
    verticalArrangement = Arrangement.spacedBy(12.dp),
) { ... }
```

### Dynamic List with Add/Remove: NOT PRESENT YET

No existing Compose code in the Android app uses `mutableStateListOf`, `items.add()`, or `items.remove()` for a visible editor. The closest pattern is the `RuntimeConfigField.options.forEach` iteration in `DeviceAgentSettingsSheet` (read-only list), which is not editable.

The MCP editor will need to introduce the first mutable list pattern in the codebase. Standard Compose approach:

```kotlin
var servers by remember { mutableStateOf(initialServers) }

// Add:
servers = servers + listOf(McpServerDraft())

// Remove at index:
servers = servers.toMutableList().apply { removeAt(index) }

// Edit at index:
servers = servers.toMutableList().apply { set(index, updated) }
```

Or equivalently with `mutableStateListOf<McpServerDraft>()`.

### Key-Value Pair Editor Pattern: NOT PRESENT YET

No existing key-value pair editor exists in the codebase. The env/headers maps in MCP will need a new pattern. Suggested design (consistent with existing style):

```kotlin
// Draft for one env/header pair
data class KvDraft(val key: String = "", val value: String = "")

// In composable:
Column {
    kvPairs.forEachIndexed { i, pair ->
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(value = pair.key, onValueChange = { ... }, modifier = Modifier.weight(1f))
            Spacer(Modifier.width(8.dp))
            OutlinedTextField(value = pair.value, onValueChange = { ... }, modifier = Modifier.weight(1f))
            RoundIconAction(icon = Lucide.X, danger = true, onClick = { remove(i) })
        }
    }
    // Add row button
    TextButton(onClick = { addPair() }) { Text("Add") }
}
```

### Segmented Control / Type Switcher Pattern

`AgentSettingsSegments` in `DeviceAgentSettingsSheet.kt:361-415` shows a segmented control (Row with weighted Box children):
```kotlin
Row(
    modifier = Modifier
        .fillMaxWidth()
        .height(42.dp)
        .clip(RoundedCornerShape(14.dp))
        .background(palette.segmentTrack)
        .padding(4.dp),
    horizontalArrangement = Arrangement.spacedBy(4.dp),
) {
    options.forEach { option ->
        val on = selected == option.value
        Box(
            modifier = Modifier
                .weight(1f)
                .fillMaxHeight()
                .shadow(if (on) 3.dp else 0.dp, RoundedCornerShape(12.dp), ...)
                .clip(RoundedCornerShape(12.dp))
                .background(if (on) palette.segmentSelected else Color.Transparent)
                .noRippleClickable { onSelect(option.value) },
            contentAlignment = Alignment.Center,
        ) { Text(option.label, ...) }
    }
}
```

This is the exact pattern for the `type` switcher (stdio / sse / http) in the MCP editor.

### Section Label Pattern

`AgentSettingsSectionLabel` (line 501-508): 11.2sp ExtraBold text in `palette.section` color, maxLines=1.

### Divider Pattern

`AgentSettingsDivider` (line 512-518): 1dp height `Box` with `background(divider color)`.

### Import: noRippleClickable

Found in `com.agentsanywhere.app.ui.designsystem.noRippleClickable` — used extensively in place of standard `clickable` modifier.

### Icon Library

`com.composables.icons.lucide.Lucide` with icons like `Lucide.X`, `Lucide.ChevronLeft`, `Lucide.Trash2`, `Lucide.Pencil`, `Lucide.Plus` (if available). Trash2 is confirmed present in `DeviceActionsSheet.kt`.

## Caveats / Not Found

- No existing mutable list editor or key-value map editor in Android code — this is net-new
- `Lucide.Plus` availability was not confirmed; `Lucide.X` is confirmed (used in DeviceAgentSettingsSheet)
