# 执行计划

## 改动文件

1. `SessionDetailState.kt` — 加 3 枚举值 + SkillItem 数据类
2. `SessionDetailController.kt` — `toSystemMessage()` 加 3 个 if 分支
3. `SessionMessages.kt` — 加 3 个 Composable + when 分支（顶层 + 子 agent）

## 步骤

### Step 1 — SessionDetailState.kt

在 `TimelineMessageKind` 枚举末尾加：
```kotlin
SkillListing,
DeferredToolsDelta,
InvokedSkills,
```

在 `TimelineMessage` data class 中加字段：
```kotlin
val skills: List<SkillItem> = emptyList(),
val addedToolNames: List<String> = emptyList(),
val removedToolNames: List<String> = emptyList(),
```

在文件中加 data class：
```kotlin
data class SkillItem(val name: String, val description: String = "", val path: String = "")
```

### Step 2 — SessionDetailController.kt

在 `toSystemMessage()` 的 `if (kind == "notification")` 块之后、fallback 之前加三个分支：

**skill_listing：**
```kotlin
if (kind == "skill_listing") {
    val skillsJson = content.records("skills")
    val skills = skillsJson.map { s ->
        SkillItem(
            name = s.text("name").orEmpty(),
            description = s.text("description").orEmpty(),
        )
    }.filter { it.name.isNotBlank() }
    if (skills.isEmpty()) return null
    return TimelineMessage(
        id = id, sourceItemId = id,
        author = MessageAuthor.Tool,
        text = "",
        status = status, type = type,
        kind = TimelineMessageKind.SkillListing,
        skills = skills,
        orderSeq = orderSeq, updatedSeq = updatedSeq,
        turnId = turnId, parentItemId = parentItemId,
    )
}
```

**deferred_tools_delta：**
```kotlin
if (kind == "deferred_tools_delta") {
    val added = content.optJSONArray("addedNames")?.let { arr ->
        (0 until arr.length()).map { arr.optString(it) }.filter { it.isNotBlank() }
    }.orEmpty()
    val removed = content.optJSONArray("removedNames")?.let { arr ->
        (0 until arr.length()).map { arr.optString(it) }.filter { it.isNotBlank() }
    }.orEmpty()
    if (added.isEmpty() && removed.isEmpty()) return null
    return TimelineMessage(
        id = id, sourceItemId = id,
        author = MessageAuthor.Tool,
        text = "",
        status = status, type = type,
        kind = TimelineMessageKind.DeferredToolsDelta,
        addedToolNames = added,
        removedToolNames = removed,
        orderSeq = orderSeq, updatedSeq = updatedSeq,
        turnId = turnId, parentItemId = parentItemId,
    )
}
```

**invoked_skills：**
```kotlin
if (kind == "invoked_skills") {
    val skillsJson = content.records("skills")
    val skills = skillsJson.map { s ->
        SkillItem(
            name = s.text("name").orEmpty(),
            path = s.text("path").orEmpty(),
        )
    }.filter { it.name.isNotBlank() }
    if (skills.isEmpty()) return null
    return TimelineMessage(
        id = id, sourceItemId = id,
        author = MessageAuthor.Tool,
        text = "",
        status = status, type = type,
        kind = TimelineMessageKind.InvokedSkills,
        skills = skills,
        orderSeq = orderSeq, updatedSeq = updatedSeq,
        turnId = turnId, parentItemId = parentItemId,
    )
}
```

### Step 3 — SessionMessages.kt

**顶层 when（line ~851）** 在 `TimelineMessageKind.Compact` 前加：
```kotlin
TimelineMessageKind.SkillListing -> SkillListingCard(message, darkMode)
TimelineMessageKind.DeferredToolsDelta -> DeferredToolsDeltaPill(message, darkMode)
TimelineMessageKind.InvokedSkills -> InvokedSkillsPill(message, darkMode)
```

**子 agent when（line ~1399）** 同样加三行。

**新增 Composable（在 ToolPlaceholder 之后）：**

```kotlin
@Composable
private fun SkillListingCard(message: TimelineMessage, darkMode: Boolean) {
    // 折叠卡片，参考 ReasoningSection 的 CollapsibleCard 模式
}

@Composable
private fun DeferredToolsDeltaPill(message: TimelineMessage, darkMode: Boolean) {
    // 小 pill，参考 CompactSeparator 的 Row 模式
}

@Composable
private fun InvokedSkillsPill(message: TimelineMessage, darkMode: Boolean) {
    // 小 pill，参考 CompactSeparator 的 Row 模式
}
```

### Step 4 — 验证

```bash
./gradlew :app:compileDebugKotlin 2>&1 | tail -20
```

## 注意

- `content.records("skills")` 是现有扩展函数，返回 `List<JSONObject>`，确认签名后使用。
- `content.optJSONArray` 是 org.json 原生方法，可直接用。
- `SkillItem` 放在 `SessionDetailState.kt` 末尾（其他 data class 之后）。
