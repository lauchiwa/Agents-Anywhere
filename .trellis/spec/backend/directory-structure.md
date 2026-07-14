# 目录结构与分层

> `server/agent_server/` 的分层职责、应用装配与依赖注入约定。

## 四层职责

| 层 | 目录 | 放什么 | 不放什么 |
|----|------|--------|----------|
| API | `api/` | `APIRouter`、请求/响应绑定、把领域异常翻成 `HTTPException` | 业务规则、直接读写数据库 |
| Service | `services/` | session/shell/terminal 等业务编排，跨仓储组合 | HTTP 细节、SQL 语句 |
| Infra | `infra/` | 数据库、文件存储、connector RPC、timeline、终端 broker | 面向用户的业务决策 |
| Core | `core/` | Pydantic 模型、认证原语、setup token、UTC 工具 | 对上层的依赖 |

判断放哪：在解析/返回 HTTP → `api`；在编排一次业务动作 → `services`；在和数据库/外部系统打交道 → `infra`；是全后端共享的稳定类型或纯函数 → `core`。

## 应用装配集中在 `app.py`

`create_app()` 是唯一的组装点。所有长生命周期对象都挂到 `app.state` 上（`store`、`rpc`、`shell_tasks`、`terminal_broker`、`terminal_stream_hub`、`timeline_broker`、`setup_token`），并在 `lifespan` 里完成 schema 初始化、connector 全部置为 offline、启动 presence 看门狗。

- 新增后台任务参考 `_connector_presence_watchdog`：`asyncio.create_task` 启动，在 `lifespan` 的 `finally` 里 `cancel` 并 await 吞掉 `CancelledError`。
- 不要在路由或 service 里自己 new 一个 `Store` / broker。它们是单例，只能来自 `app.state`。

参考文件：`agent_server/app.py`。

## 依赖注入统一走 `deps.py`

路由通过 `Depends(get_xxx)` 拿服务，绝不自己构造。`deps.py` 里的 `get_*` 函数从 `conn.app.state` 取单例，或用单例组合出每请求一份的 service：

```python
def get_store(conn: HTTPConnection) -> Store:
    return conn.app.state.store

def get_session_run_service(conn: HTTPConnection) -> SessionRunService:
    return SessionRunService(conn.app.state.store, conn.app.state.rpc)
```

- 只需要「调用者是谁」用 `current_user_id`（不查库，纯解 token）；需要角色/是否禁用再用 `current_user`。
- 新增 service 时，在 `deps.py` 加一个 `get_xxx`，不要在路由里手动拼装依赖。

参考文件：`agent_server/deps.py`。

## 命名约定

- 路由模块按产品资源命名：`sessions.py` / `auth.py` / `connectors.py` / `approvals.py`，跟 URL 前缀对齐。
- 仓储 mixin 命名为 `XxxRepositoryMixin`，文件放 `infra/repositories/`。
- 私有模块级 helper 用前导下划线（`_raise_session_run_error`、`_timeline_item_from_input`）。
