# 编码规范总索引

> Agents Anywhere 的分层编码规范。改动某一层的代码前，先读该层的 `index.md`，再按主题深入。规范都从仓库真实源码取证，不是通用框架建议。

## 项目分层

Agents Anywhere 是「用手机/浏览器远程控制别的设备上编程 Agent」的控制面，代码按运行角色分层：

| 层 | 目录 | 角色 | 技术栈 |
|----|------|------|--------|
| 后端 | `server/` | 控制面：鉴权、用户、connector 生命周期、session、timeline、审批、文件元数据、终端代理、RPC 派发 | Python 3.12 · FastAPI · SQLAlchemy Core · Pydantic v2 |
| 连接器 | `connector/` | 跑在拥有工作区的机器上，发现并驱动本地 Codex / Claude 运行时，把归一化状态回传后端 | Python 3.12 · claude-agent-sdk · websockets · httpx |
| 前端 | `web-next/` | Web 控制台：session/device/审批/文件/终端管理 | TypeScript · Next.js 16 · React 19 · next-intl · Tailwind |
| Android | `android/` | Android 客户端 | Kotlin · Jetpack Compose |

后端与连接器都是 Python，但职责相反：后端是「云端控制面」，连接器是「本地执行端」，两者通过 WebSocket + JSON-RPC 对接。运行时本身（Codex / Claude）只存在于连接器所在的机器上。

## 规范导航

| 层 | 规范入口 |
|----|----------|
| 后端 | [backend/index.md](./backend/index.md) |
| 连接器 | [connector/index.md](./connector/index.md) |
| 前端 | [frontend/index.md](./frontend/index.md) |
| 思维引导（跨层通用） | [guides/index.md](./guides/index.md) |

Android 层的分层规则单独维护在仓库里的 [`android/ARCHITECTURE.md`](../../android/ARCHITECTURE.md)，未纳入本目录。

## 跨层改动

新增一个 event 类型、JSONL 记录、RPC 载荷或配置字段时，改动通常会同时穿过 connector（产生）→ backend（存储/派发）→ frontend/android（消费）。动手前先读 [guides/cross-layer-thinking-guide.md](./guides/cross-layer-thinking-guide.md)，避免只改一端导致跨层错位。

## 维护约定

- 每条重要规则都要能指向真实源码文件或反复出现的本地模式，不写通用套话。
- 新增/删除/重命名规范文件后，同步更新对应的 `index.md`，保持导航与文件集一致。
- 全部用简体中文书写（代码符号、文件路径、命令保持原文）。
