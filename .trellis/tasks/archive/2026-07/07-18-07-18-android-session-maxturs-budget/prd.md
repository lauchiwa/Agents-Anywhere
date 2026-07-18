# Android 会话 maxTurns 设置字段

## Goal

`SessionRuntimeSettingsSheet` 缺少 `maxTurns` 会话覆盖字段。服务端 schema 已将 `maxTurns`（number 类型，`allowSessionOverride=True`）纳入 Claude 运行时配置，`DeviceAgentSettingsSheet` 也已支持，但 `SessionRuntimeSettingsSheet` 只处理 enum 类型字段，数字字段被忽略。

`maxBudgetUsd` 是 per-turn 参数，非 session schema 字段，本任务不处理。

## Requirements

1. 在 `ModelPage`（`SessionRuntimeSettingsSheet` 的主页）的 MCP servers 行**上方**渲染 `maxTurns` 数字输入框（schema 有该字段且 `allowSessionOverride=true` 时才显示）。
2. 输入框：`OutlinedTextField`，`keyboardType=Number`，空值发 null（清除覆盖），非空发 Int。
3. `patchRuntimeSetting(key, value)` 在 `SessionDetailScreen` 从 `(String, String?)` 改为 `(String, Any?)`，以便将 Int 正确传给 `patchRuntimeSettings(Map<String, Any?>)`。
4. `SessionRuntimeSettingsSheet.onPatch` 及所有内部函数签名同步改为 `(String, Any?)` -> Unit`。
5. 所有现有 enum 字段行为不变。

## Acceptance Criteria

- [ ] `ModelPage` 在 schema 含 `maxTurns` 时显示数字输入框
- [ ] 输入数字后以 Int 发送给服务端，清空时以 null 发送
- [ ] `./gradlew :app:compileDebugKotlin` 编译成功
- [ ] permissionMode / model / effort 字段行为不受影响
