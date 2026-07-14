# 前端开发规范（web-next/）

> 本目录规范面向 `web-next/` 下的 Next.js Web 控制台。改动前端代码前先读本文件，再按主题深入。

Web 控制台是 Agents Anywhere 的桌面端操作面：管理 session、device、审批、文件、终端和远程控制流程。它是纯前端应用，所有数据都来自后端 `server/` 的 HTTP API。

## 技术栈

- Next.js `16.2.10`（App Router，`app/[locale]/` 结构，Turbopack）。
- React `19.2.0`，客户端组件为主（仓库里 `"use client"` 超过 90 处）。
- TypeScript `~5.9`，严格类型，禁止裸 `any`。
- next-intl `^4.8`：双语（`en` / `zh-CN`），路由与文案都走它。
- Radix UI primitives + Tailwind CSS v4 + `cva` 组合式组件。
- react-markdown `^10` + remark-gfm 渲染消息正文。
- 依赖用 Yarn 4（corepack）管理，声明在 `web-next/package.json`。

## 规范索引

| 文档 | 说明 |
|------|------|
| [目录结构](./directory-structure.md) | `src/` 分层、路由结构、模块归位 |
| [组件规范](./component-guidelines.md) | 组件拆分、`"use client"`、动态加载、Radix + cva |
| [Hook 规范](./hook-guidelines.md) | 数据获取、轮询/分页、副作用清理 |
| [状态管理](./state-management.md) | 本地状态、Context、乐观更新、服务端状态合并 |
| [类型安全](./type-safety.md) | 类型集中定义、API 泛型、untyped payload 处理 |
| [质量规范](./quality-guidelines.md) | 禁用模式、i18n 约束、验证命令 |

## 验证命令

改完前端代码后，在 `web-next/` 目录跑：

```bash
yarn typecheck
yarn lint
yarn build
```

`yarn build` 会做完整静态导出，Docker 镜像打包时也走同一条构建路径，因此本地 build 通过是合并的前置条件。
