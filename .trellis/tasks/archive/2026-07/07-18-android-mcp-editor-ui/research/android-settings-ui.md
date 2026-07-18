# Research: Android Settings UI (DeviceAgentSettingsSheet + SessionRuntimeSettingsSheet)

- **Query**: Layout patterns, API call patterns, where to add MCP config in Android
- **Scope**: internal
- **Date**: 2026-07-18

## Findings

### Files Found

| File Path | Description |
|---|---|
| `android/app/src/main/java/com/agentsanywhere/app/ui/screens/devices/DeviceAgentSettingsSheet.kt` | Connector-level agent settings sheet (best template for MCP connector editor) |
| `android/app/src/main/java/com/agentsanywhere/app/ui/screens/sessiondetail/SessionRuntimeSettingsSheet.kt` | Session-level runtime settings sheet |
| `android/app/src/main/java/com/agentsanywhere/app/ui/screens/devices/DeviceDetailControls.kt` | Shared UI components: SheetTextButton, RoundIconAction |

### DeviceAgentSettingsSheet — Structure

Signature (line 67–73):
```kotlin
internal fun DeviceAgentSettingsSheet(
    device: AgentDevice,
    agent: DeviceDetailAgent,
    onDismiss: () -> Unit,
    onLoadSettings: suspend (String, String) -> Result<RuntimeSettingsState>,
    onPatchSettings: suspend (String, String, Map<String, Any?>) -> Result<RuntimeSettingsState>,
)
```

- `ModalBottomSheet` with `skipPartiallyExpanded = true`
- `RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp)`
- Outer `Column` with `navigationBarsPadding()` and `padding(start=22, end=22, top=10, bottom=20)`
- `verticalArrangement = Arrangement.spacedBy(12.dp)`
- Handle: `AgentSettingsHandle` (42×5dp pill in center of 12dp height box)
- Header row: title text + subtitle + `RoundIconAction(Lucide.X)` close button (38dp circle)
- Body: `AgentSettingsBody` (scrollable Column with `heightIn(max = bodyMaxHeight)`)
- Footer: `SheetTextButton` (primary=true, fillMaxWidth)
- `bodyMaxHeight = screenHeightDp * 0.58f`

Loading state: centered `CircularProgressIndicator(size=24dp, strokeWidth=2dp)` in 220dp height box.
Error state: centered text in 180dp height box.
Save error: 44dp height `Row` with `background(errorSurface)` and `border(errorBorder)`.

### Palette Pattern

Both sheets use a `private data class XxxPalette(...)` with all colors, and a `private fun xxxPalette(darkMode: Boolean): XxxPalette` function. Dark mode is detected by `colors.canvas == Color(0xFF09090B)`.

Dark palette uses zinc-900 range; light palette uses warm whites/grays.

### SessionRuntimeSettingsSheet — Structure

- Same `ModalBottomSheet` pattern
- Two-page navigation (`RuntimeSheetPage.Model` / `RuntimeSheetPage.ModeEffort`) via `var page by remember`
- `SheetHandle` (5×42dp pill) + `SheetHomeIndicator` (5×134dp pill at bottom)
- `SheetHeader` with leading/trailing icon buttons

### Shared Controls (DeviceDetailControls.kt)

**SheetTextButton** (line 26–66):
- 44dp height, `CircleShape`, `widthIn(min=104dp)`, `padding(horizontal=20dp)`
- `primary=true` → dark/light contrasting background; `primary=false` → subtle surface with border

**RoundIconAction** (line 69–111):
- 38dp circle with border
- `danger=true` → red-tinted surface/border/icon
- Icon size: 16dp

### Where MCP Config Belongs

**Connector-level**: The MCP editor sheet for a connector should be accessible from `DeviceDetailScreen`. The existing "Agent settings" button in `DeviceDetailScreen` opens `DeviceAgentSettingsSheet` — there should be a separate "MCP servers" button that opens a new `ConnectorMcpServersSheet`.

**Session-level**: The session-level MCP editor should be accessible from `SessionDetailScreen`, analogous to how `SessionRuntimeSettingsSheet` is opened. A new `SessionMcpServersSheet` would follow the same `ModalBottomSheet` pattern.

### LocalAAColors Usage

`LocalAAColors.current` provides `colors.canvas`, `colors.ink`, `colors.border` used for generic tints. The individual sheets define their own palette on top.

## Caveats / Not Found

- `DeviceDetailScreen.kt` was found but not fully read — the exact trigger point for a new MCP button needs a quick read of that file
- No existing "MCP" entry point in any screen was found
