# Technical Design: attachment 通道解析

## 1. 问题根因

SDK `get_session_messages()` 内部只保留 `message` 键存在的条目（JSONL 条目 → `raw_message = getattr(message, "message", None)` → `if not isinstance(raw_message, dict): return None`）。JSONL 里的 attachment 条目格式为：
```json
{ "attachment": {...}, "parentUuid": "...", "uuid": "...", ... }
```
没有 `message` 键，直接被 drop。

## 2. 修复策略：两步读取

`history_adapter.py` 中已有两个 SDK 调用：
- `_get_session_info(sdk, session_id)` → 返回 session 的目录/元信息
- `_get_session_messages(sdk, session_id)` → 返回无 attachment 的消息列表

新增第三步：**直接读取原始 JSONL 文件**，提取 attachment 条目。

JSONL 文件路径由 `session_info.path`（或 `session_info.directory + session_id + ".jsonl"`）确定。可以用 SDK 的 `get_session_info()` 拿到路径，或通过 `_get_session_info` 的返回值属性 `path`/`file_path` 得到。

### 2.1 attachment 条目提取函数

```python
def _read_attachment_entries(session_info: Any) -> list[dict[str, Any]]:
    """Read raw attachment entries directly from the JSONL transcript."""
    # session_info.path or session_info.file_path
    path = _string_attr(session_info, "path") or _string_attr(session_info, "file_path")
    if not path or not os.path.exists(path):
        return []
    result = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict): continue
            att = entry.get("attachment")
            if not isinstance(att, dict): continue
            att_type = att.get("type", "")
            if att_type not in _SUPPORTED_ATTACHMENT_TYPES:
                continue
            result.append({
                "uuid": entry.get("uuid") or att_type,  # fallback id
                "parentUuid": entry.get("parentUuid"),
                "session_id": entry.get("session_id") or entry.get("sessionId", ""),
                "timestamp": entry.get("timestamp", ""),
                "attachment": att,
            })
    return result
```

`_SUPPORTED_ATTACHMENT_TYPES = {"skill_listing", "deferred_tools_delta", "invoked_skills"}`

### 2.2 归一化（normalizers.py）

`ClaudeTranscriptNormalizer.normalize()` 接收 `raw_events: list[dict[str, Any]]`，现在需要同时接收 `attachment_entries`。

**方案**：在 `normalize()` 内部，对 attachment 条目产出新的 `NormalizedClaudeEvent`，`blockType` 为 attachment 子类型。但 normalizer 当前只处理 `message.content` 块，attachment 是独立结构。

为了最小改动，选择**在 history_adapter 直接生成 system timeline item**（绕过 normalizer/reducer），和 compact_boundary 处理方式类似。

### 2.3 直接生成 timeline item（绕过 normalizer/reducer）

在 `_timeline_items_from_messages()` 中：
1. 调 `_read_attachment_entries(session_info)` 
2. 对每个 attachment 条目，调 `_attachment_to_timeline_item()` 生成 system item
3. 将 attachment items 插入到对应 turn 内、紧接 user message 之后（按 parentUuid 匹配）

```python
def _attachment_to_timeline_item(
    entry: dict[str, Any],
    session_id: str,
    external_session_id: str,
    turn_id: str,
    order_seq: int,
) -> dict[str, Any] | None:
    att = entry["attachment"]
    att_type = att.get("type", "")
    uuid = entry.get("uuid") or att_type
    content = _normalize_attachment_content(att_type, att)
    if content is None:
        return None
    item_id = f"claude_attachment_{uuid}"
    return {
        "id": item_id,
        "sessionId": session_id,
        "turnId": turn_id,
        "type": "system",
        "status": "done",
        "role": None,
        "parentItemId": None,
        "content": content,
        "source": {"kind": "attachment", "sessionId": external_session_id},
        "orderSeq": order_seq,
        "revision": 1,
        "createdAt": entry.get("timestamp") or utc_now(),
        "updatedAt": entry.get("timestamp") or utc_now(),
    }
```

```python
def _normalize_attachment_content(att_type: str, att: dict[str, Any]) -> dict[str, Any] | None:
    if att_type == "skill_listing":
        content_text = att.get("content", "")
        skills = _parse_skill_listing(content_text)
        if not skills:
            return None  # 空 skill_listing 静默忽略
        return {"kind": "skill_listing", "skills": skills}
    if att_type == "deferred_tools_delta":
        added = att.get("addedNames", [])
        removed = att.get("removedNames", [])
        if not added and not removed:
            return None
        return {"kind": "deferred_tools_delta", "addedNames": added, "removedNames": removed}
    if att_type == "invoked_skills":
        skills = att.get("skills", [])
        if not skills:
            return None
        return {"kind": "invoked_skills", "skills": [{"name": s.get("name", ""), "path": s.get("path", "")} for s in skills if isinstance(s, dict)]}
    return None
```

`skill_listing` 文本格式：`"- name: description\n- name2: desc2"` → 按行 parse：

```python
def _parse_skill_listing(text: str) -> list[dict[str, str]]:
    result = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("- "): continue
        line = line[2:]
        if ": " in line:
            name, _, desc = line.partition(": ")
        else:
            name, desc = line, ""
        result.append({"name": name.strip(), "description": desc.strip()})
    return result
```

### 2.4 插入 orderSeq

attachment 插入时机：在 turn 的 user message 之后、assistant 消息之前。简化策略：在每个 turn 结束后把该 turn 的 attachment items 以 `parentUuid` 匹配追加，若无法匹配则追加到 turn 末尾。

实际上，attachment 的 `parentUuid` 指向 user message，大多数是 turn 的第一个 item。由于 orderSeq 只影响显示顺序，把 attachment item 排在 turn 开始后紧接 user prompt 是最合理的。

### 2.5 判断 session_info.path

用以下辅助：
```python
def _session_jsonl_path(session_info: Any) -> str | None:
    for attr in ("path", "file_path", "transcript_path"):
        val = _string_attr(session_info, attr)
        if val and val.endswith(".jsonl") and os.path.exists(val):
            return val
    return None
```

## 3. Web 渲染（session-timeline-entry.tsx）

`SystemCard` 已有 `kind === "notification"` 等分支，加三个：

```tsx
if (kind === "skill_listing") return <SkillListingEntry item={item} />
if (kind === "deferred_tools_delta") return <DeferredToolsDeltaEntry item={item} />
if (kind === "invoked_skills") return <InvokedSkillsEntry item={item} />
```

各组件极简实现（无 i18n）：
- `SkillListingEntry`：折叠区，book 图标 + "N skills available"，展开列 name: description
- `DeferredToolsDeltaEntry`：单行 `+N deferred tools available`（addedNames.length > 0）
- `InvokedSkillsEntry`：单行 `Skill: name1, name2`（names 列表）

## 4. 不做的决策

- `task_reminder`：实测全空，实现成本高于价值，skip
- `hook_additional_context`：属于系统 prompt 注入，不适合出现在用户可见时间线
- `file` / `compact_file_reference`：已有独立渲染路径，不重复
- `date_change` / `command_permissions` / `queued_command`：低价值噪声
- Android 端：独立后续任务

## 5. 测试覆盖

- `test_history_adapter_reads_attachment_entries`：mock session_info.path → 解析出 skill_listing / deferred_tools + 过滤空 task_reminder
- `test_attachment_content_normalizer_skill_listing`：文本 parse 正确
- `test_attachment_content_normalizer_deferred_tools_delta`：addedNames/removedNames
- `test_attachment_content_normalizer_invoked_skills`：skills 列表
- `test_attachment_content_normalizer_ignores_unknown`：未知子类型返回 None
