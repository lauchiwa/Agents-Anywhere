# PRD: Web 端 maxBudgetUsd 输入 UI

## Background

`sendSessionMessage` 已支持 `maxBudgetUsd` 字段（类型 `number`，透传给 connector→SDK），但 Web UI 没有任何入口让用户设置这个值。目前只能通过 API 直接传入。

`maxBudgetUsd` 是单次消息的 USD 预算上限，控制 Claude SDK 每次 turn 允许花费的最大金额。设置后 SDK 会在接近上限时自动截断。

## Requirements

### 1. 预算输入控件

在 `SessionComposer` 工具栏（`flex flex-wrap items-center gap-1 px-3 pb-3 pt-2` 行）中增加一个 **Budget** 按钮/输入区，位于 Attachment 按钮之后、Permission/Model 选择器之前。

**交互设计：**
- 默认状态：显示一个小型 Ghost 按钮，标签为 `"$ Budget"` 或 `"No limit"`（当未设置时）；设置后显示 `"$X.XX"`
- 点击后：按钮变为一个 inline 数字输入框（`<input type="number">`），宽约 80-90px，`min=0`，`step=0.5`，`placeholder="no limit"`
- 输入框失焦或按 Enter 时：解析值，合法则保存，非法（NaN/负数）则清空（视为无限制）
- 输入框旁显示一个 × 清除按钮，点击后清空并恢复按钮状态

### 2. 状态管理

- `maxBudgetUsd` 作为 `SessionComposer` 内部 state（`useState<number | null>`），初始值 `null`（无限制）
- 不持久化到 localStorage（每次进入 session 重置）

### 3. 传递到 send

`SessionComposer` 的 `onSend` 签名不变（`(content, attachments) => Promise<boolean>`）。  
改为由 `SessionComposer` 内部在调用 `onSend` 前将 `maxBudgetUsd` 附加。

但 `session-detail.tsx` 的 `handleSend` 负责实际调用 `sendSessionMessage`，因此需要其中一种方案：

**方案A（推荐）**：将 `onSend` 签名扩展为 `(content, attachments, options?: { maxBudgetUsd?: number | null }) => Promise<boolean>`，`SessionComposer` 传入 maxBudgetUsd，`session-detail.tsx` 透传给 `sendSessionMessage`。

**方案B**：在 `SessionComposer` 外层 `session-detail.tsx` 用 ref 读取 composer 内部的 budget state（更复杂，不推荐）。

采用**方案A**。

### 4. i18n

在 `messages/en.json` 和 `messages/zh-CN.json` 的 `dashboard.session` 命名空间下新增：
- `budgetLabel`: `"Budget"` / `"预算"`
- `budgetNoLimit`: `"No limit"` / `"不限"`
- `budgetPlaceholder`: `"no limit"` / `"不限"`

### 5. 样式约束

- 复用已有 `Button` (variant=ghost, size=sm, className="h-8 ...") 风格，与 Permission/Model 按钮一致
- 数字输入框使用 `Input` 组件（shadcn/ui），`className="h-8 w-20 text-sm"`
- 只在 `session.takeover && connectorOnline` 时可交互（与发送按钮条件一致）

## Constraints

- 不引入新依赖
- `onSend` 回调扩展需向后兼容（options 参数可选）
- 不改动 `task-composer.tsx`（它有自己独立的发送逻辑，不涉及此功能）

## Acceptance Criteria

- [ ] Composer 工具栏显示 Budget 按钮，未设置时显示 "No limit"
- [ ] 点击后可输入数字，失焦/Enter 保存，无效值清空
- [ ] 设置后按钮显示 `$X.XX`，× 可清除
- [ ] 发送消息时 `maxBudgetUsd` 被正确传入 `sendSessionMessage`
- [ ] `tsc --noEmit` 通过
- [ ] 未设置时（null）不传 `maxBudgetUsd` 字段（保持现有行为）
