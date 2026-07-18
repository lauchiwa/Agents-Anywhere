# UI 优化：高优先级问题修复

## 目标

修复本次审计发现的最高优先级 UI 问题，覆盖 Web 前端和 Android 两端。

## 范围

### Android（高优先级 4 项）

1. **动作菜单图标错配** — Fork/Tag/Delete 三个菜单项图标语义全错
   - Fork 当前用 rename 图标、Tag 当前用 unpin 图标、Delete 当前用 archive 图标
   - 文件：`HomeScreen.kt` L575–584

2. **会话标题 15 字符强制截断** — 删除 `sessionDisplayTitle()` 函数，改由 `Text` 的 `maxLines=1 + TextOverflow.Ellipsis` 处理
   - 文件：`HomeScreen.kt` L128、L737–740

3. **折叠状态刷新重置** — `pinnedExpanded`/`recentExpanded` 改用 `rememberSaveable`，不绑定 sessions key
   - 文件：`HomeScreen.kt` L1422–1423

4. **SkillListingCard 展开箭头用 Unicode 字符** — 改用 `ChevronDown`/`ChevronRight` Lucide 图标
   - 文件：`SessionMessages.kt` L1761

### Web 前端（高优先级 3 项）

5. **侧边栏每条目挂载 3 个 Dialog** — 将 Delete AlertDialog + Tag Dialog + Rename Dialog 提升到列表父层，仅渲染一个实例
   - 文件：`app-sidebar.tsx` L449–692

6. **`filtered` sessions 未 `useMemo`** — 补 `useMemo` 缓存
   - 文件：`app-sidebar.tsx` L115

7. **`PermissionCard` compact 圆角类冲突** — 改为条件渲染 `compact ? "rounded-lg" : "rounded-xl"`
   - 文件：`session-approval-card.tsx` L80

## 验收标准

- [ ] Android：动作菜单 Fork/Tag/Delete 图标语义正确
- [ ] Android：会话标题在列表中自然 Ellipsis 截断，不再 15 字符硬截断
- [ ] Android：切换 pinned/recent 折叠后刷新会话列表，折叠状态保持
- [ ] Android：SkillListingCard 展开/折叠图标改用 ChevronDown/ChevronRight
- [ ] Web：100 条会话时 DOM 中只有 1 套 Dialog
- [ ] Web：`filtered` 通过 useMemo 缓存
- [ ] Web：PermissionCard compact 模式圆角正确为 `rounded-lg`
- [ ] TypeScript 编译无新增错误，Android 编译成功
