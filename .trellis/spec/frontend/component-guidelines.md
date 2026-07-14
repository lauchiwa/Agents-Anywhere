# 组件规范

> React 组件的结构、props、样式与可访问性约定，取证自 `web-next/src/components/`。

## 组件结构

- 需要浏览器 API / hook 的组件在文件首行标注 `"use client"`（全仓约 91 处），纯展示的 server 组件不标。
- 用具名函数导出：`export function TimelineEntry({ ... }: { ... }) { ... }`。props 类型直接内联在参数上，简单组件无需单独 `type Props`。
- 一个文件可以放一个主组件 + 若干仅本文件使用的私有子组件（小写不导出），例如 `session-timeline-entry.tsx` 里的 `MessageCard` / `SystemCard` / `ReasoningEntry`。

参考文件：`web-next/src/components/session/session-timeline-entry.tsx`。

## 按 `type` / `kind` 分发渲染

时间线条目这类多态数据，用“早返回 + 分发”而不是一个巨型 JSX：

```tsx
if (item.type === "turn.start" || item.type === "turn.end") return null
if (item.type === "message") return <MessageCard ... />
if (item.type === "tool") return <ToolCard ... />
```

新增一种条目类型时，加一个分支 + 一个私有卡片组件，不要在既有卡片里塞 `if`。

## 重量级组件用 `next/dynamic` 懒加载

Markdown 渲染器依赖较重且只在客户端有意义，用动态导入并关掉 SSR：

```tsx
const MarkdownText = dynamic(
  () => import("../markdown-text").then((mod) => ({ default: mod.MarkdownText })),
  { ssr: false },
)
```

参考文件：`web-next/src/components/session/session-timeline-entry.tsx:17`。

## 样式用 Tailwind + `cn()`

- 样式一律 Tailwind 原子类，条件类名用 `@/lib/utils` 的 `cn()`（`clsx` + `tailwind-merge`）合并，不要手拼模板字符串。
- 例：`cn("flex min-w-0 max-w-full", isUser && "justify-end")`。
- 颜色只用语义化 token（`bg-secondary`、`text-muted-foreground`、`border-destructive/35`），不要写死 `#hex` 或具体色值，以兼容明暗主题。

## 折叠/展开用 `components/ui/collapsible`

工具结果、reasoning、artifact 等“默认收起、按需展开”的块统一用 Radix `Collapsible`（`CollapsibleTrigger` + `CollapsibleContent`），触发器里放一个随 `data-[state=open]` 旋转的 `ChevronDown`。不要自己用 `useState` 造展开逻辑。

参考文件：`web-next/src/components/session/session-timeline-entry.tsx` 的 `ReasoningEntry` / `ArtifactCard`。

## 传插槽而不是反向依赖

当父卡片需要嵌套子内容又要避免循环 import 时，父组件把子节点作为 `childrenContent?: React.ReactNode` 传进去（子代理输出嵌套到父 `ToolCard` 就是这么做的），而不是让底层卡片反向 import 上层分发器。

参考文件：`web-next/src/components/session/session-timeline-entry.tsx:44-69`。

## 常见错误

- 直接用 `next/link` / `next/navigation` 跳转，丢掉 locale 前缀 → 用 `@/i18n/routing`。
- 在组件里写死中英文文案 → 用 `useTranslations`（见 hook 规范）。
- 在 server 组件里用 `useState`/`useEffect` 却忘了 `"use client"`。
