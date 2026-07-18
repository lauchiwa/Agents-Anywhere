# PRD：Web 会话列表搜索

## 背景

`WorkspaceContext` 已有 `search` 状态、`setSearch` setter、`filterSessions` 过滤逻辑。
侧边栏头部有一个 `<Search>` 图标按钮（app-sidebar.tsx:126–133），但无 onClick、无输入框——纯占位符。

## 目标

把占位符变成真正可用的搜索输入，连接已有的 `setSearch` 状态。

## 需求

### 功能
1. 点击 Search 图标后展开一个内联搜索输入框（不跳页面，不弹 modal）
2. 输入框获得焦点；键入内容实时更新 `setSearch`，`filterSessions` 自动重新过滤
3. 按 Escape 或点击输入框右侧 ✕ 清空并收起搜索
4. 搜索范围：`title`（已有）+ `tag`（新增一行）+ `cwd`（新增一行，取 basename）
5. 搜索无结果时复用现有 `empty.noSessionsMatch` 提示
6. Pinned 区同样受搜索过滤（搜索时连 pinned 区也过滤）

### UX
- 搜索激活时，图标区域替换为输入框 + ✕ 按钮，与 sidebar 宽度一致
- 非激活时恢复图标按钮；`search` 不为空时图标用 `text-foreground`（与 filter active 风格一致）
- 不在 sidebar header 新增新行；复用现有高度

### i18n
- 使用已有 `t("dashboard.actions.search")` 作为 placeholder 和 aria-label
- ✕ 按钮 aria-label 使用 `t("common.clear")`（需新增）或 `t("common.cancel")`（已有）

## 验收标准

- [ ] 点击 Search 图标展开输入框，autofocus
- [ ] 实时过滤 pinned + recents 两组
- [ ] Escape 收起并清空
- [ ] ✕ 按钮清空并收起
- [ ] `filterSessions` 扩展至搜索 tag 和 cwd basename
- [ ] TypeScript noEmit 通过
- [ ] en.json / zh-CN.json 无缺 key

## 范围约束

- 仅修改 `app-sidebar.tsx`、`workspace-context.tsx`（filterSessions）、`messages/en.json`、`messages/zh-CN.json`
- 不做模糊搜索（精确 substring，大小写不敏感即可）
- 不做服务端搜索
- 不改动路由或 URL

## 不在范围内

- 按 tag / device / runtime 的专项搜索 tab
- 搜索历史记录
- Android 侧
