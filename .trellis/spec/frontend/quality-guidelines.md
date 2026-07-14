# 质量规范

> 前端的禁用/必用模式与验证命令，取证自 `web-next/`。

## 验证命令

改完前端代码后，在 `web-next/` 目录跑：

```bash
yarn typecheck   # tsc --noEmit
yarn lint        # next lint (eslint 9 + eslint-config-next)
yarn build       # next build，打生产镜像时会执行，构建期报错会阻断发布
```

> 打包生产 Docker 镜像时会把 `web-next` 一起 `yarn build` 进镜像，所以前端的类型/构建错误会在镜像构建阶段暴露。提交前务必本地跑通 `yarn build`。

## 必用模式

- 请求走 `DashboardApi` / `lib/api` 的 `ApiClient`，不手写 `fetch`。
- 跳转走 `@/i18n/routing` 的 `Link` / `useRouter`，保住 locale 前缀。
- 面向用户文案走 `useTranslations`，`en.json` 与 `zh-CN.json` 同步补齐。
- 条件类名走 `cn()`；颜色走语义 token。
- 需要浏览器能力的组件标 `"use client"`。

## 禁用模式

- 禁 `any`（用 `unknown` + 类型守卫）。
- 禁在组件里写死双语文案或色值。
- 禁用 `next/link` / `next/navigation` 直接跳转。
- 禁把只用一次的逻辑提前抽成公共 hook / 组件。

## 无自动化测试，靠类型 + 构建把关

`web-next` 目前没有单测框架（`package.json` 无 test 脚本）。质量底线是 `typecheck` + `lint` + `build` 三条命令全绿，外加对改动路径的手动验证（尤其是会话时间线的渲染）。新增复杂纯逻辑（如时间线分组/去重）时，优先把它写成 `features/` 或 `session/*.ts` 里的纯函数，便于将来补测与就地推理。

## Code Review 检查清单

- 后端字段改动是否同步到了 `features/dashboard/types.ts` 及所有消费方？
- 新文案是否两种 locale 都补了？
- 是否误用了裸 `fetch` / 裸 `next/link` / 硬编码颜色？
- 重组件是否需要 `dynamic(..., { ssr: false })`？
- 派生数据是否用 `useMemo` 而非 `useEffect` 同步 state？
