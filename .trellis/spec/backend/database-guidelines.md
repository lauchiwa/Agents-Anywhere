# 数据库规范

> `Store` 门面 + mixin 仓储、SQLite/PostgreSQL 双后端、timeline 写入锁。

## 单一门面 `Store`

所有数据访问都走 `Store`（`infra/repositories/facade.py`）。它不是一个「god object」，而是把一堆 `XxxRepositoryMixin` 组合到一个类里，每个 mixin 只负责一个资源域：

```python
class Store(
    AgentCatalogRepositoryMixin,
    UserRepositoryMixin,
    ConnectorRepositoryMixin,
    SessionRepositoryMixin,
    TimelineRepositoryMixin,
    ApprovalRepositoryMixin,
    ...
):
```

- 新增一个资源域：在 `infra/repositories/` 建 `xxx.py`，写一个 `XxxRepositoryMixin`，然后加进 `facade.py` 的基类列表。
- 不要在 service / 路由里直接 new SQLAlchemy 引擎或写裸 SQL。数据访问统一从 `Store` 的方法进。
- `Store` 是单例，构造一次挂在 `app.state.store`，通过 `deps.get_store` 注入。

参考文件：`agent_server/infra/repositories/facade.py`、`agent_server/infra/repositories/`（各 mixin）。

## SQLAlchemy Core，不用 ORM

项目用 SQLAlchemy **Core**（`Table` + `select()/insert()/update()/delete()`），不用声明式 ORM。表定义集中在 `infra/db/`，查询通过异步引擎执行：

```python
async with self._engine.connect() as conn:      # 只读
    rows = (await conn.execute(select(...))).mappings().all()

async with self._engine.begin() as conn:         # 需要事务/写入
    await conn.execute(insert(...), values)
```

- 只读用 `engine.connect()`，写入/多语句用 `engine.begin()`（自动提交/回滚）。
- 取字典行用 `.mappings()`，避免按位置索引。

参考文件：`agent_server/infra/timeline_store.py`。

## 双后端：SQLite 与 PostgreSQL

同一套代码要同时能在 SQLite（本地开发默认）和 PostgreSQL（生产）上跑。后端类型在 `Store` 构造时由 `build_engine` 决定，存到 `self.backend`。

- **写方言相关代码时必须分支处理**。upsert 是典型例子：`SqlTimelineStore.upsert_one` 按 `self._backend` 选择 `sqlite_insert` 或 `pg_insert`，两者的 `on_conflict_do_update` 用法不同。
- JSON 序列化统一走 `_json_dumps`（`ensure_ascii=False, sort_keys=True, separators=(",", ":")`），保证内容哈希稳定、跨后端一致。
- 不要假设自增主键行为、返回值语义在两个后端一致；拿不准就在两个后端都验证。

参考文件：`agent_server/infra/timeline_store.py`（`upsert_one`）、`agent_server/infra/db/engine.py`。

## Schema 初始化是幂等的、可脱离 lifespan

`Store.__init__` 在构造时就同步建表并 seed 只读目录（`init_db_sync` + `_seed_agent_catalog_sync` + `seed_runtime_config_schemas_sync`），这样测试可以直接 `Store(...)` 而不必进 FastAPI lifespan。

- seed 必须**幂等**：按主键判存量、只插缺失行（见 `_seed_table_sync`）。重复跑 seed 不能报错也不能重复插。
- 改 seed 数据（模型/模式目录）时保持这个幂等契约。

参考文件：`agent_server/infra/repositories/store_support.py`（`_seed_agent_catalog_sync` / `_seed_table_sync`）。

## Timeline 写入必须串行化

同一个 session 的 timeline 是并发写热点（connector 每个流式增量都写）。写入必须包在 `_timeline_lock(session_id)` 里：

- **SQLite**：进程内 `asyncio.Lock`，按 `session_id` 分桶。单 worker 部署够用（开源默认）。
- **PostgreSQL**：`pg_advisory_lock`，在专用连接上持有整个临界区，跨 uvicorn worker 安全。

PostgreSQL 路径带三段计时诊断（checkout / acquire / hold），超阈值打 `warning`——这是为了定位「timeline 写入卡死拖垮整台设备」这类问题留下的探针。改动锁逻辑时保留这些诊断，不要吞掉 `pg_advisory_lock` 的异常。

参考文件：`agent_server/infra/repositories/timeline.py`（`_timeline_lock`）。

## 常见错误

- 在 service 或路由里直接建引擎、写裸 SQL，绕过 `Store`。
- 写 upsert / JSON 只测了 SQLite，忘了 PostgreSQL 方言差异。
- 改 seed 破坏幂等（无条件 insert 导致重复跑报错）。
- 并发写 timeline 时绕过 `_timeline_lock`。
