# Hook 规范

> 自定义 hook、数据获取与国际化 hook 的约定，取证自 `web-next/src/`。

## 数据获取：`useState` + `useEffect` + `DashboardApi`

项目没有引入 React Query / SWR。数据获取的本地模式是：组件内用 `useState` 存数据/加载/错误，`useEffect` 里调用 `DashboardApi` 方法，用 `useCallback` 包裹可复用的加载函数。请求一律经过 `features/dashboard/api.ts` 的 `DashboardApi`，它内部走 `lib/api` 的 `ApiClient`。

组件里不要直接 `fetch`，也不要自己拼 URL 和 header——鉴权、query 序列化、错误归一都在 `ApiClient.request` 里做了。

参考文件：`web-next/src/lib/api/client.ts`、`web-next/src/features/dashboard/api.ts`。

## 通用 hook 放 `hooks/`，一次性 hook 就地定义

- 跨组件复用的放 `web-next/src/hooks/`，如 `use-mobile.ts`（媒体查询）、`use-toast.ts`（全局 toast）。
- 只服务某个组件的 hook 直接写在该组件文件里，不必上升到 `hooks/`。

## 国际化文案用 `useTranslations`

面向用户的文案一律通过 next-intl 的 `useTranslations(namespace)` 取，按命名空间组织：

```tsx
const tSession = useTranslations("dashboard.session")
// ...
<span>{tSession("reasoning")}</span>
```

文案本身放仓库根 `web-next/messages/en.json` 与 `zh-CN.json`，两个文件的 key 必须一一对应。新增文案要同时补两份，不能只加一种语言。

参考文件：`web-next/src/components/session/session-timeline-entry.tsx` 的 `ReasoningEntry`、`web-next/messages/zh-CN.json`。

## 命名约定

- hook 一律 `use` 前缀 + camelCase：`useMobile`、`useToast`、`useTranslations`。
- 文件名 kebab-case：`use-mobile.ts`。

## 常见错误

- 在组件里手写 `fetch` 或拼 `Authorization` header → 走 `DashboardApi` / `ApiClient`。
- 新增文案只加了 `en.json` 忘了 `zh-CN.json`（或反之）→ 构建/运行时会出现缺失 key。
- 把只用一次的 hook 提到 `hooks/` 造成无谓的公共面积。
