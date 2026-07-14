# 后端开发规范（server/）

> 本目录规范面向 `server/` 下的 FastAPI 后端。改动后端代码前先读本文件，再按主题深入。

后端是 Agents Anywhere 的控制面：负责鉴权、用户、connector 生命周期、session、timeline 状态、审批、文件元数据、终端代理，以及向 connector 派发 RPC。运行时本身（Codex / Claude）不在这里，而在 `connector/`。

## 技术栈

- Python 3.12+，异步优先（`async def` + `await`）。
- FastAPI（`>=0.136`）+ Uvicorn，应用工厂 `agent_server.app:create_app`。
- SQLAlchemy Core（异步引擎）+ 双后端：本地开发用 SQLite（aiosqlite），生产用 PostgreSQL（asyncpg）。
- Pydantic v2 定义所有 API 数据模型（`core/models.py`）。
- loguru 做日志。
- 依赖用 `uv` 管理，声明在 `server/pyproject.toml`。

## 规范索引

| 文档 | 说明 |
|------|------|
| [目录结构](./directory-structure.md) | 分层职责、模块归位、依赖注入约定 |
| [数据库规范](./database-guidelines.md) | Store 门面 + mixin 仓储、双后端、timeline 锁 |
| [错误处理](./error-handling.md) | 领域异常 → HTTPException 的边界翻译 |
| [日志规范](./logging-guidelines.md) | loguru 惰性占位、日志级别、RPC 日志回传 |
| [质量规范](./quality-guidelines.md) | 禁用模式、类型约定、验证命令 |

## 验证命令

改完后端代码后，在 `server/` 目录跑：

```bash
uv run ruff check . --exclude .venv
uv run pytest -q
```
