# 类型安全

> 类型组织、后端契约与类型收窄约定，取证自 `web-next/src/`。

## 后端契约类型集中在 `features/<domain>/types.ts`

所有与后端 JSON 对应的类型定义在 `features/dashboard/types.ts`（`SessionView`、`TimelineItem`、`ConnectorView`、各类 `*Response` 等），`api.ts` 和组件都从这里 import。新增/修改后端字段时，改这一个文件，所有消费方随之收敛。

`TimelineItem.parentItemId?: string | null` 就是这样跨层新增的一个可选字段——先在 types.ts 加字段，组件再消费。

参考文件：`web-next/src/features/dashboard/types.ts`。

## 用 `type` 别名 + 字面量联合，不用 enum

领域取值一律用字符串字面量联合类型，例如：

```ts
export type SessionStatusValue = "idle" | "running" | "waiting_approval" | "error"
export type ApiErrorKind = "network" | "http" | "unauthorized" | "forbidden" | ...
```

这与后端字符串枚举一一对应，序列化零成本。不要引入 TS `enum`。

参考文件：`web-next/src/features/dashboard/types.ts`、`web-next/src/lib/api/errors.ts`。

## 处理 `unknown` 用类型守卫收窄

来自网络/外部的数据先按 `unknown` 收，再用运行时判断收窄，不要直接断言。`extractErrorPayload(payload: unknown)` 是范例：逐层 `typeof` 判断后才取字段。时间线内容里散落的 `textOf` / `recordsOf` / `firstTextOf`（`components/session/session-utils.ts`）也是同一思路——把 `item.content` 里的不确定字段安全地取成字符串/数组。

参考文件：`web-next/src/lib/api/errors.ts`、`web-next/src/components/session/session-utils.ts`。

## 错误对象用 `ApiError` + `isApiError`

后端错误统一抛 `ApiError`（带 `status` / `kind` / `detail` / `code`），捕获侧用 `isApiError(error)` 守卫后再取字段，展示文案用 `errorMessage(error, fallback)` 兜底。

参考文件：`web-next/src/lib/api/errors.ts`。

## 禁用/慎用

- 禁 `any`。不确定的外部数据用 `unknown` + 守卫。
- 少用 `as` 断言；只有在类型守卫已保证安全、或消费后端已知契约（如 `payload as T`，且已过 `response.ok` 判断）时才用。
- 组件 props 就近内联类型即可，不必为每个组件都抽 `interface`。
