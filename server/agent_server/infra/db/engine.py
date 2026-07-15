from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from agent_server.infra.db.schema import metadata

SQLITE_BACKEND = "sqlite"
POSTGRES_BACKEND = "postgres"


def resolve_db_url(*, backend: str | None = None, url: str | None = None, sqlite_path: str | Path | None = None) -> tuple[str, str]:
    """Return (backend, async_url) from explicit args or env vars.

    Precedence:
      1. AGENT_SERVER_DB_URL — explicit SQLAlchemy URL wins.
      2. AGENT_SERVER_DB_BACKEND + (AGENT_SERVER_DB for sqlite).
      3. Legacy AGENT_SERVER_DB — defaults to sqlite at that path.
    """
    url = url if url is not None else os.environ.get("AGENT_SERVER_DB_URL")
    backend = backend if backend is not None else os.environ.get("AGENT_SERVER_DB_BACKEND")
    legacy = sqlite_path if sqlite_path is not None else os.environ.get("AGENT_SERVER_DB")

    if url:
        resolved_backend = backend or _infer_backend_from_url(url)
        return resolved_backend, url

    if backend == POSTGRES_BACKEND:
        raise ValueError(
            "AGENT_SERVER_DB_BACKEND=postgres requires AGENT_SERVER_DB_URL "
            "(e.g. postgresql+asyncpg://user:pass@host:5432/dbname)"
        )

    path = str(legacy or "agent-server.sqlite3")
    return SQLITE_BACKEND, f"sqlite+aiosqlite:///{path}"


def _infer_backend_from_url(url: str) -> str:
    if url.startswith("postgresql"):
        return POSTGRES_BACKEND
    if url.startswith("sqlite"):
        return SQLITE_BACKEND
    raise ValueError(f"unsupported AGENT_SERVER_DB_URL scheme: {url}")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def build_engine(*, backend: str | None = None, url: str | None = None, sqlite_path: str | Path | None = None) -> tuple[str, AsyncEngine]:
    resolved_backend, async_url = resolve_db_url(backend=backend, url=url, sqlite_path=sqlite_path)
    engine_kwargs: dict[str, object] = {"future": True}
    if resolved_backend == SQLITE_BACKEND:
        # Async DB-API connections are bound to the event loop that opened
        # them. FastAPI/Starlette's TestClient uses anyio to run requests in
        # fresh loop scopes, so SQLite keeps NullPool to avoid reusing
        # connections across loops. Postgres should use SQLAlchemy's default
        # async pool; opening a new TCP connection per checkout is too costly
        # for production request latency.
        engine_kwargs["poolclass"] = NullPool
    else:
        # Postgres pool hardening. Without this the engine runs on the library
        # defaults (pool_size=5, max_overflow=10, no liveness check, no idle
        # recycle) and has no server-side timeout on lock waits. That's the
        # failure mode behind "session stops updating, then the list won't
        # refresh": one half-dead TCP connection (silently dropped by a cloud
        # PG / NAT / firewall while idle) gets handed out, a statement on it
        # hangs forever, and — because the connector WS ingest loop is serial —
        # that one hang freezes heartbeats, RPC responses, and further timeline
        # writes for the whole device. pre_ping validates a connection before
        # handing it out; recycle proactively retires old ones; lock_timeout /
        # statement_timeout turn an infinite wait into a fast, retryable error.
        #
        # All knobs are env-overridable so operators can tune per deployment
        # without a code change.
        #
        # Sizing: the ceiling that matters is Postgres `max_connections`, which
        # is SHARED across every client of the instance (this app + any other
        # tenant DBs + the superuser + autovacuum workers). On a small shared PG
        # (e.g. max_connections=50, tight RAM) an over-large pool both starves
        # the other tenants and risks OOM (~5-10MB per PG backend). So the
        # defaults are deliberately modest: 5 persistent + up to 10 burst = 15
        # per worker, well under a 50-connection instance even with a second
        # tenant. The workload is single-worker and mostly serial per connector,
        # so 15 is ample; raise it only after the diagnostic logs show real
        # checkout waits. Rule of thumb: (pool_size + max_overflow) * workers,
        # summed across ALL apps on the instance, must stay under
        # max_connections with headroom for the superuser and maintenance.
        engine_kwargs["pool_size"] = _env_int("AGENT_SERVER_DB_POOL_SIZE", 5)
        engine_kwargs["max_overflow"] = _env_int("AGENT_SERVER_DB_MAX_OVERFLOW", 10)
        engine_kwargs["pool_timeout"] = _env_int("AGENT_SERVER_DB_POOL_TIMEOUT", 30)
        engine_kwargs["pool_recycle"] = _env_int("AGENT_SERVER_DB_POOL_RECYCLE", 1800)
        engine_kwargs["pool_pre_ping"] = True
        # server_settings are applied per asyncpg connection. lock_timeout caps
        # how long a statement (e.g. pg_advisory_lock) waits to acquire a lock;
        # statement_timeout caps total statement runtime. 0 disables. We default
        # statement_timeout to 0 (off) to avoid killing legitimately long work,
        # and set a bounded lock_timeout since lock waits are the observed hang.
        lock_timeout_ms = _env_int("AGENT_SERVER_DB_LOCK_TIMEOUT_MS", 15000)
        statement_timeout_ms = _env_int("AGENT_SERVER_DB_STATEMENT_TIMEOUT_MS", 0)
        server_settings: dict[str, str] = {}
        if lock_timeout_ms > 0:
            server_settings["lock_timeout"] = str(lock_timeout_ms)
        if statement_timeout_ms > 0:
            server_settings["statement_timeout"] = str(statement_timeout_ms)
        connect_args: dict[str, object] = {}
        if server_settings:
            connect_args["server_settings"] = server_settings
        # Bound how long establishing a new connection may block. Combined with
        # pool_pre_ping (which validates before handing a pooled connection out)
        # this keeps a dead/slow peer from stalling a checkout indefinitely.
        connect_args["timeout"] = _env_int("AGENT_SERVER_DB_CONNECT_TIMEOUT", 10)
        if connect_args:
            engine_kwargs["connect_args"] = connect_args
    engine = create_async_engine(async_url, **engine_kwargs)
    if resolved_backend == SQLITE_BACKEND:
        _enable_sqlite_fk(engine)
    return resolved_backend, engine


def _enable_sqlite_fk(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001 — SQLAlchemy event signature
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        await _ensure_compat_schema_async(conn)


def init_db_sync(async_url: str) -> None:
    """Run metadata.create_all from a sync context.

    Useful at startup when there is no event loop yet (e.g. during app
    construction). Idempotent — uses CREATE TABLE IF NOT EXISTS semantics.

    For sqlite we use a transient sync engine (no extra driver required).
    For other backends we spin up a transient async engine on a fresh event
    loop so users don't need to install a separate sync driver (e.g. psycopg2)
    just for schema setup.
    """
    if async_url.startswith("sqlite+aiosqlite:") or async_url.startswith("sqlite:"):
        sync_url = (
            "sqlite:" + async_url[len("sqlite+aiosqlite:"):]
            if async_url.startswith("sqlite+aiosqlite:")
            else async_url
        )
        sync_engine = create_engine(sync_url, future=True)

        @event.listens_for(sync_engine, "connect")
        def _on_connect(dbapi_conn, _record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()

        try:
            metadata.create_all(sync_engine)
            with sync_engine.begin() as conn:
                _ensure_compat_schema_sync(conn)
        finally:
            sync_engine.dispose()
        return

    import asyncio
    import threading

    async def _run() -> None:
        engine = create_async_engine(async_url, future=True)
        try:
            await init_db(engine)
        finally:
            await engine.dispose()

    # Run on a worker thread so this works whether the caller is in a running
    # event loop (e.g. inside an async test) or not. asyncio.run() refuses to
    # nest into an existing loop, so we spin up a private one in a thread.
    captured: list[BaseException] = []

    def _runner() -> None:
        try:
            asyncio.run(_run())
        except BaseException as exc:  # noqa: BLE001 — propagate any failure
            captured.append(exc)

    thread = threading.Thread(target=_runner, name="init-db-sync")
    thread.start()
    thread.join()
    if captured:
        raise captured[0]


async def _ensure_compat_schema_async(conn) -> None:  # noqa: ANN001 - SQLAlchemy connection
    if not await _column_exists_async(conn, "sessions", "origin"):
        await conn.execute(text("ALTER TABLE sessions ADD COLUMN origin TEXT NOT NULL DEFAULT 'connector_import'"))
    if not await _column_exists_async(conn, "sessions", "context_usage_json"):
        await conn.execute(text("ALTER TABLE sessions ADD COLUMN context_usage_json TEXT"))
    if not await _column_exists_async(conn, "sessions", "rate_limit_json"):
        await conn.execute(text("ALTER TABLE sessions ADD COLUMN rate_limit_json TEXT"))


async def _column_exists_async(conn, table: str, column: str) -> bool:  # noqa: ANN001 - SQLAlchemy connection
    if conn.dialect.name == SQLITE_BACKEND:
        rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).all()
        return any(row[1] == column for row in rows)
    rows = (
        await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        )
    ).all()
    return bool(rows)


def _ensure_compat_schema_sync(conn) -> None:  # noqa: ANN001 - SQLAlchemy connection
    if not _column_exists_sync(conn, "sessions", "origin"):
        conn.execute(text("ALTER TABLE sessions ADD COLUMN origin TEXT NOT NULL DEFAULT 'connector_import'"))
    if not _column_exists_sync(conn, "sessions", "context_usage_json"):
        conn.execute(text("ALTER TABLE sessions ADD COLUMN context_usage_json TEXT"))
    if not _column_exists_sync(conn, "sessions", "rate_limit_json"):
        conn.execute(text("ALTER TABLE sessions ADD COLUMN rate_limit_json TEXT"))


def _column_exists_sync(conn, table: str, column: str) -> bool:  # noqa: ANN001 - SQLAlchemy connection
    if conn.dialect.name == SQLITE_BACKEND:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).all()
        return any(row[1] == column for row in rows)
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).all()
    return bool(rows)
