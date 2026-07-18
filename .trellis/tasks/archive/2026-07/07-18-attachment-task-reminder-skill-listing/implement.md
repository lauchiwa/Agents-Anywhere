# Implement Plan

## 执行顺序

### Step 1：连接器 — history_adapter.py

1. 加 `import json, os`（如未有）
2. 加 `_SUPPORTED_ATTACHMENT_TYPES = frozenset({"skill_listing", "deferred_tools_delta", "invoked_skills"})`
3. 加 `_session_jsonl_path(session_info)` — 从 session_info 取 JSONL 路径
4. 加 `_parse_skill_listing(text)` — 文本行 → list[{name, description}]
5. 加 `_normalize_attachment_content(att_type, att)` — 三种子类型→content dict
6. 加 `_read_attachment_entries(session_info)` — 读 JSONL → filtered attachment list
7. 加 `_attachment_to_timeline_item(entry, session_id, external_session_id, turn_id, order_seq)` → timeline item
8. 修改 `_timeline_items_from_messages()`：
   - 先调 `_read_attachment_entries(session_info)` 建 `{parentUuid: [entries]}` 映射
   - 在每个 turn 处理结束、收集 reduced items 后，把匹配该 turn 内任何 item uuid 的 attachment items 追加
   - 若无 parentUuid 或无法匹配，追加到 turn 末尾（turn.end 之前）

### Step 2：连接器 — 测试

文件：`tests/test_history_adapter_attachments.py`（新文件）

测试用例：
- `test_read_attachment_entries_returns_supported_types`
- `test_read_attachment_entries_filters_unsupported`
- `test_parse_skill_listing_parses_name_and_description`
- `test_parse_skill_listing_handles_empty`
- `test_normalize_attachment_content_skill_listing`
- `test_normalize_attachment_content_deferred_tools_delta`
- `test_normalize_attachment_content_invoked_skills`
- `test_normalize_attachment_content_ignores_unknown`
- `test_normalize_attachment_content_ignores_empty_skill_listing`

### Step 3：验证检查点

```bash
cd connector && .venv/bin/python -m pytest tests/test_history_adapter_attachments.py -v
cd connector && .venv/bin/python -m pytest --tb=short -q
```

### Step 4：Web — session-timeline-entry.tsx

在 `SystemCard` 里加三个 kind 分支和对应组件：
1. `SkillListingEntry` — 折叠面板，`Book` 图标，展开显示 skill 名+描述
2. `DeferredToolsDeltaEntry` — 单行 badge，显示 `+N / -M tools`
3. `InvokedSkillsEntry` — 单行，显示 `Skills: name1, name2`

### Step 5：验证检查点

```bash
cd web-next && npx tsc --noEmit
```

### Step 6：质检

- connector 214+ passed
- server 220+ passed（不改服务端，应无变化）
- web tsc 通过

## 回滚点

- history_adapter 改动：attachment item orderSeq 若排序有误，可调整 `_timeline_items_from_messages` 中 append 位置
- web 渲染：三个新 component 如有样式问题，可快速回退 SystemCard 分支
