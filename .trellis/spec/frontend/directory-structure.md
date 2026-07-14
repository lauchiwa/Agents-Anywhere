# 目录结构与分层

> `web-next/src/` 的目录职责、模块归位与命名约定。

## 顶层目录职责

| 目录 | 放什么 | 不放什么 |
|------|--------|----------|
| `app/` | Next.js App Router 路由：`app/[locale]/` 下的 `layout.tsx` / `page.tsx`，以及 `login` / `setup` / `pair` 等路由段 | 复杂业务组件（放 `components/`）、数据请求封装（放 `features/` 或 `lib/api`） |
| `components/` | 可复用 React 组件。领域组件直接放根，通用基元放 `components/ui/`，会话相关子域放 `components/session/` | 后端请求细节、纯数据转换 |
| `features/` | 按业务域组织的数据层：API 封装（`features/dashboard/api.ts`）、类型（`types.ts`）、纯数据 helper（`attachments.ts`） | Compose/JSX、视觉样式 |
| `lib/` | 与业务无关的基础设施：HTTP 客户端（`lib/api/`）、`cn()` 样式合并、剪贴板、下载、高亮等工具 | 业务域类型、页面状态 |
| `hooks/` | 跨域复用的通用 hook（`use-mobile.ts`、`use-toast.ts`） | 只服务单个组件的一次性 hook（就地定义即可） |
| `i18n/` | next-intl 的路由与 request 配置（`routing.ts`、`request.ts`、`client-locale.ts`） | 文案本身（放仓库根 `messages/*.json`） |

## App Router 是 `[locale]` 动态段

路由根是 `app/[locale]/`，locale 取值由 `i18n/routing.ts` 的 `defineRouting` 声明（`["en", "zh-CN"]`，默认 `en`）。跨页面跳转用 `i18n/routing.ts` 导出的 `Link` / `redirect` / `useRouter`，不要直接用 `next/link`、`next/navigation`，否则会丢掉 locale 前缀。

参考文件：`web-next/src/i18n/routing.ts`。

## 组件按“域 → 子域 → 基元”分层

- 领域组件放 `components/` 根，例如 `session-detail.tsx`、`session-list.tsx`、`app-shell.tsx`。
- 会话时间线这种大子域单独建目录 `components/session/`，内部再拆卡片（`session-tool-cards.tsx`）、条目分发（`session-timeline-entry.tsx`）、乐观更新（`optimistic-timeline.ts`）。
- 设计系统基元放 `components/ui/`（shadcn/radix 风格），如 `collapsible`、`scroll-area`。业务组件从这里取原子件组合，不要自己造。

## 数据层集中在 `features/<domain>/`

`features/dashboard/` 是范例：`api.ts` 定义 `DashboardApi` 类封装所有端点，`types.ts` 定义全部后端契约类型，`attachments.ts` / `runtime-config.ts` 放纯函数转换。组件从 `@/features/dashboard/types` 取类型、从 `@/features/dashboard/api` 取请求，不在组件里手写 `fetch`。

参考文件：`web-next/src/features/dashboard/api.ts`、`web-next/src/features/dashboard/types.ts`。

## 命名约定

- 文件名一律 kebab-case：`session-tool-cards.tsx`、`use-mobile.ts`。
- 组件导出用 PascalCase 具名导出（`export function SessionDetail(...)`），页面级动态导入除外。
- 纯逻辑/类型文件用 `.ts`，含 JSX 的用 `.tsx`。
- 路径别名统一走 `@/`（映射到 `src/`），不要写 `../../` 深层相对路径。
