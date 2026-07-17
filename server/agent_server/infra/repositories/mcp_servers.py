from __future__ import annotations

from typing import Any

from agent_server.infra.repositories.store_support import *


class McpServersRepositoryMixin:
    async def get_connector_mcp_servers(self, connector_id: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT mcp_servers_json FROM connectors WHERE id = :id"),
                    {"id": connector_id},
                )
            ).one_or_none()
        if row is None:
            return None
        raw = _json_loads(row[0])
        return raw if isinstance(raw, dict) else None

    async def set_connector_mcp_servers(
        self, connector_id: str, servers: dict[str, Any]
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("UPDATE connectors SET mcp_servers_json = :v WHERE id = :id"),
                {"v": _json_dumps(servers), "id": connector_id},
            )

    async def get_session_mcp_servers(self, session_id: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT mcp_servers_json FROM sessions WHERE id = :id"),
                    {"id": session_id},
                )
            ).one_or_none()
        if row is None:
            return None
        raw = _json_loads(row[0])
        return raw if isinstance(raw, dict) else None

    async def set_session_mcp_servers(
        self, session_id: str, servers: dict[str, Any]
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("UPDATE sessions SET mcp_servers_json = :v WHERE id = :id"),
                {"v": _json_dumps(servers), "id": session_id},
            )

    async def get_effective_mcp_servers(
        self,
        session_id: str,
        connector_id: str,
    ) -> dict[str, Any]:
        from agent_server.core.runtime_config import merge_mcp_servers
        connector_mcp = await self.get_connector_mcp_servers(connector_id)
        session_mcp = await self.get_session_mcp_servers(session_id)
        return merge_mcp_servers(connector_mcp, session_mcp)
