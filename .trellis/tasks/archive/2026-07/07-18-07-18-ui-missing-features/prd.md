# UI 高优先级功能补全

按审计优先级实现，分 4 批：

## 批次 1：快速修复（Quick Wins）

### W1. Web AI 消息复制按钮
- 现状：AI 助手回复消息（`MessageCard`）没有复制按钮
- 要求：hover 时在消息右上角显示 Copy 图标按钮，复制纯文本内容
- 文件：`session-timeline-entry.tsx`

### W2. Web ToolCard running 时自动展开
- 现状：所有工具卡片默认折叠，运行中的工具也看不到实时输出
- 要求：`status === "running"` 的 ToolCard `defaultOpen=true`
- 文件：`session-tool-cards.tsx` L68

### W3. Web ToolRunGroup 含 approval 时自动展开
- 现状：含待审批 approval 的工具组默认折叠，审批卡片被遮住
- 要求：组内有对应 pending approval 时初始展开
- 文件：`session-detail.tsx` L1094

### A1. Android 工具输出去掉 DisableSelection，加复制按钮
- 现状：`ToolActivityDetailCard` 展开内容用 `DisableSelection` 禁止选择
- 要求：去掉 DisableSelection，在展开区域右上角加复制图标按钮
- 文件：`SessionMessages.kt` L1349

## 批次 2：会话列表状态徽章

### A2. Android 会话列表行状态指示器
- 现状：列表行没有任何状态区分（running/waiting_approval/error 一样）
- 要求：行右侧时间戳左边加状态徽章：
  - running → 绿色脉冲动画点
  - waiting_approval → 橙色实心点
  - error → 红色感叹号小图标
- 文件：`HomeScreen.kt` L1608、L1668

### W4. Web 侧边栏状态点视觉强化
- 现状：running 已是实心绿，但 waiting_approval/error 是空心圈，6px 下几乎无法区分
- 要求：waiting_approval 改为实心琥珀 `bg-amber-400`，error 改为实心红 `bg-red-500`
- 文件：`app-sidebar.tsx` L469

## 批次 3：工具输出展开

### W5. Web 工具代码框展开/折叠按钮
- 现状：`CodePanelFrame` 高度硬限 320px，无展开入口
- 要求：右上角 actions 区加"展开/折叠"切换按钮（↕ 图标），展开后解除 maxHeight 限制
- 文件：`session-tool-cards.tsx` L629

### A3. Android 命令输出超长折叠
- 现状：`CommandPreviewSection` 全量渲染无限制
- 要求：默认折叠超过 25 行，底部显示"显示全部 N 行"按钮
- 文件：`SessionMessages.kt` L1582

## 批次 4：会话详情顶部操作菜单（最复杂）

### W6. Web 会话详情顶部加三点操作菜单
- 现状：顶部栏无 Fork/Delete/Archive/Pin/Tag 入口
- 要求：顶部栏右侧加 DropdownMenu（三点图标），包含 Fork/Archive/Pin/Tag/Delete，行为与侧边栏右键菜单对齐
- 文件：`session-view-header.tsx`

### A4. Android 会话详情顶部加溢出菜单
- 现状：顶部栏只有 Runtime Settings 和 Agent Files 两个按钮
- 要求：右侧加三点 MoreVertical 图标，下拉菜单含 Fork/Archive/Rename/Delete
- 文件：`SessionDetailHeader.kt`

## 验收标准

- [ ] Web: AI 消息 hover 时显示复制按钮，点击复制文本
- [ ] Web: 运行中工具卡片自动展开
- [ ] Web: 含 pending approval 的工具组自动展开
- [ ] Android: 工具调用展开内容可以选择文字，有复制按钮
- [ ] Android: 会话列表行显示 running/approval/error 状态徽章
- [ ] Web: 侧边栏 waiting_approval/error 状态点为实心
- [ ] Web: 工具代码框有展开/折叠按钮
- [ ] Android: 超长命令输出默认折叠超 25 行
- [ ] Web: 会话详情顶部有三点菜单，含完整会话操作
- [ ] Android: 会话详情顶部有溢出菜单
- [ ] TypeScript 编译无新增错误，Android 编译成功
