from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from connector.logging import logger

from connector.attachments import attachment_target
from connector.adapter import NotificationSink
from connector.claude.history_adapter import ClaudeHistoryAdapter
from connector.claude.mcp_config import load_servers as load_mcp_servers
from connector.claude.normalized import NormalizedClaudeEvent
from connector.claude.normalizers import ClaudeLiveNormalizer
from connector.claude.timeline_identity import ClaudeTimelineIdentity
from connector.claude.timeline_reducer import ClaudeTimelineReducer, is_task_event_tool_name
from connector.launch import LaunchTarget, launch_target
from connector.time import utc_now


AttachmentDownloader = Callable[[str, str], Awaitable[tuple[bytes, str, str]]]
"""(session_id, file_id) -> (data, original_name, media_type)"""

McpConfigProvider = Callable[[], dict[str, dict[str, Any]]]
"""Returns `{server_name: McpServerConfig}` dict for the SDK's `mcp_servers`.

Called on every turn so hand-edits to `mcp.json` take effect without a
connector restart. Failures should degrade to `{}` (no MCP) rather than
crashing the turn — see `_safe_mcp_config`."""

_MAX_STDERR_LINES = 80
_MAX_STDERR_CHARS = 8000
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|auth[_-]?token|authorization|bearer|token|password|secret)([=:\s]+)([^\s,;]+)"
)


class ClaudeSdkAdapterError(RuntimeError):
    pass


@dataclass(slots=True)
class _PendingSdkApproval:
    approval_id: str
    future: asyncio.Future[str]
    input_data: dict[str, Any]
    tool_name: str = ""
    # For AskUserQuestion: {question_text: answer_string | [answer_string, ...]}.
    # Injected into the tool's updated_input so the CLI feeds the choices back to
    # the model instead of "The user did not answer the questions."
    answers: dict[str, Any] | None = None


@dataclass(slots=True)
class _SdkSessionRuntime:
    session_id: str
    connector_id: str | None = None
    cwd: str | None = None
    external_session_id: str | None = None
    client: Any | None = None
    active_task: asyncio.Task[None] | None = None
    active_turn_id: str | None = None
    next_order_seq: int = 1
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_approvals: dict[str, _PendingSdkApproval] = field(default_factory=dict)
    interrupted: bool = False
    stderr_lines: list[str] = field(default_factory=list)
    current_client_message_id: str | None = None
    current_content: str | None = None
    current_attachments: list[dict[str, Any]] | None = None
    emitted_user_message: bool = False
    partial_message_id: str | None = None
    partial_message_uuid: str | None = None
    partial_text_blocks: dict[int, str] = field(default_factory=dict)
    # Per-content-block-index type ("text" | "thinking"), registered on
    # content_block_start. Thinking and text blocks of one assistant message
    # share a single continuous index space, so we can only tell a thinking
    # delta apart from a text delta by remembering the index's block type.
    partial_block_types: dict[int, str] = field(default_factory=dict)
    live_stream_items: dict[str, dict[str, Any]] = field(default_factory=dict)
    live_tool_items: dict[str, dict[str, Any]] = field(default_factory=dict)
    ignored_task_tool_use_ids: set[str] = field(default_factory=set)
    # Sub-agent (Agent/Task tool) live progress. These arrive as SDK
    # TaskStarted/Progress/Notification/Updated messages that exist ONLY in the
    # real-time stream (never in the transcript JSONL), so they can't ride the
    # shared normalizer/reducer path — they are merged straight into the parent
    # Agent tool card's content.subagent here. subagent_progress accumulates the
    # progress dict per parent tool_use_id; subagent_task_to_tool maps a task_id
    # back to its tool_use_id for TaskUpdated messages, which carry only task_id.
    subagent_progress: dict[str, dict[str, Any]] = field(default_factory=dict)
    subagent_task_to_tool: dict[str, str] = field(default_factory=dict)
    # "Approve for this session" grants. Keyed by a hash of tool_name + the
    # canonicalized tool input (see _approval_rule_key), NOT including turn_id,
    # so the grant survives across turns within the same session. Deliberately
    # parameter-exact: approving `Bash("npm test")` never auto-allows
    # `Bash("rm -rf /")`. The set lives on the per-session runtime, so a new
    # session (or a connector restart) starts empty — old grants never leak.
    session_approved_rules: set[str] = field(default_factory=set)
    # Latest context-window usage gauge (from client.get_context_usage()), a
    # session-level snapshot carried on session.updated so clients can show a
    # "context 68% · near autocompact" indicator. Distinct from per-turn usage,
    # which rides the turn.end timeline item.
    context_usage: dict[str, Any] | None = None
    # Latest rate-limit snapshot (from the SDK's RateLimitEvent, emitted when the
    # CLI's throttling state changes). Carried on session.updated as rateLimit so
    # clients can warn "quota almost full, resets at X" or "rate limited". Sticky
    # until a later event supersedes it; an "allowed" event clears it to None so
    # the warning disappears once throttling lifts.
    rate_limit: dict[str, Any] | None = None
    # Set when the user approves an ExitPlanMode tool call: the permission mode to
    # switch back to (execution) once plan mode ends. Carried on the next
    # session.updated as permissionMode so the server persists it to the session
    # override and later turns run in execute mode instead of re-entering plan.
    pending_permission_mode: str | None = None


@dataclass(slots=True)
class ClaudeSdkAdapter:
    """Claude Chat Mode adapter backed by the Python Claude Agent SDK."""

    notification_sink: NotificationSink = None
    sdk_module: Any | None = None
    history_adapter: ClaudeHistoryAdapter = field(default_factory=ClaudeHistoryAdapter)
    attachment_downloader: AttachmentDownloader | None = None
    claude_target: LaunchTarget | None = None
    # Provider hook for MCP server configs. Called per-turn from
    # `_options_kwargs` so hand-edits to `mcp.json` take effect on the next
    # turn without a connector restart. Default reads `~/.agent-server/mcp.json`
    # (or the `AGENT_CONNECTOR_MCP_CONFIG` env override). Tests inject a
    # closure over an in-memory dict to keep the filesystem out of the picture.
    mcp_config_provider: McpConfigProvider | None = None
    _sessions: dict[str, _SdkSessionRuntime] = field(default_factory=dict, init=False)

    @property
    def claude_bin(self) -> str | None:
        return self.claude_target.path if self.claude_target is not None else None

    @claude_bin.setter
    def claude_bin(self, value: str | None) -> None:
        self.claude_target = launch_target("cli", value) if value else None

    def forget_sync_state(self) -> None:
        self.history_adapter.forget_sync_state()

    def forget_persisted_sync_state(self, connector_id: str) -> None:
        self.history_adapter.forget_persisted_sync_state(connector_id)

    def apply_history_sync_state(self, state: list[dict[str, Any]]) -> None:
        self.history_adapter.apply_history_sync_state(state)

    async def create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = (
            _optional_string(params.get("sessionId"))
            or f"sess_claude_chat_{secrets.token_urlsafe(10)}"
        )
        runtime = self._runtime_for(session_id, params)
        return {
            "sessionId": session_id,
            "externalSessionId": runtime.external_session_id,
            "backendNotifications": [],
        }

    async def sync_session(self, params: dict[str, Any]) -> dict[str, Any]:
        self._prepare_history_adapter()
        return await self.history_adapter.sync_session(params)

    async def sync_existing_sessions(
        self,
        connector_id: str,
        *,
        limit: int = 100,
        force: bool = False,
        notification_sink: Callable[[list[dict[str, Any]]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        self._prepare_history_adapter()
        skip_external_session_ids = {
            runtime.external_session_id
            for runtime in self._sessions.values()
            if runtime.active_turn_id is not None and runtime.external_session_id is not None
        }
        return await self.history_adapter.sync_existing_sessions(
            connector_id,
            limit=limit,
            force=force,
            skip_external_session_ids=skip_external_session_ids,
            notification_sink=notification_sink,
        )

    async def start_turn(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _required(params, "sessionId")
        content = _required(params, "content")
        runtime = self._runtime_for(session_id, params)
        connector_id = _optional_string(params.get("connectorId"))
        if connector_id is not None:
            runtime.connector_id = connector_id
        if runtime.lock.locked():
            raise ClaudeSdkAdapterError("Claude SDK turn already running for this session")
        await runtime.lock.acquire()
        runtime.interrupted = False
        turn_id = _optional_string(params.get("turnId")) or _turn_id(session_id, content)
        runtime.active_turn_id = turn_id
        runtime.current_client_message_id = _optional_string(params.get("clientMessageId"))
        runtime.current_content = content
        runtime.current_attachments = _attachments_metadata(params)
        runtime.emitted_user_message = False
        runtime.partial_message_id = None
        runtime.partial_message_uuid = None
        runtime.partial_text_blocks.clear()
        runtime.partial_block_types.clear()
        runtime.live_stream_items.clear()
        runtime.live_tool_items.clear()
        runtime.ignored_task_tool_use_ids.clear()
        runtime.subagent_progress.clear()
        runtime.subagent_task_to_tool.clear()
        runtime.active_task = asyncio.create_task(
            self._drive_turn(runtime=runtime, params=params, content=content, turn_id=turn_id)
        )
        self._prepare_history_adapter()
        runtime.active_task.add_done_callback(
            lambda _task: runtime.lock.release() if runtime.lock.locked() else None
        )
        return {"turnId": turn_id}

    async def interrupt_turn(self, params: dict[str, Any]) -> dict[str, Any]:
        runtime = self._sessions.get(_required(params, "sessionId"))
        if runtime is None:
            return {"interrupted": False, "reason": "session not registered"}
        runtime.interrupted = True
        for pending in list(runtime.pending_approvals.values()):
            if not pending.future.done():
                pending.future.set_result("cancelled")
        client = runtime.client
        if client is not None:
            interrupt = getattr(client, "interrupt", None)
            if callable(interrupt):
                await interrupt()
                return {"interrupted": True}
        return {"interrupted": False, "reason": "no active Claude SDK client"}

    async def set_model(self, params: dict[str, Any]) -> dict[str, Any]:
        # Switch the model on the in-flight client so it takes effect mid-turn.
        # The persisted override (server side) is what makes the change stick for
        # later turns; this RPC only handles the live client. An empty/None model
        # resets to the SDK default. No active client -> a readable failure, not
        # a crash (the override still applies to the next turn).
        return await self._apply_runtime_setting(
            params,
            method_name="set_model",
            value=_optional_string(params.get("model")),
            allow_none=True,
        )

    async def set_permission_mode(self, params: dict[str, Any]) -> dict[str, Any]:
        # Switch the permission mode on the in-flight client (default / acceptEdits
        # / plan / bypassPermissions / dontAsk / auto). Same contract as set_model:
        # live-only, degrades cleanly when no client is running.
        mode = _optional_string(params.get("permissionMode") or params.get("mode"))
        if not mode:
            return {"applied": False, "reason": "permissionMode is required"}
        return await self._apply_runtime_setting(
            params,
            method_name="set_permission_mode",
            value=mode,
            allow_none=False,
        )

    async def stop_task(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _required(params, "sessionId")
        task_id = _optional_string(params.get("taskId"))
        if not task_id:
            return {"ok": False, "reason": "taskId is required"}
        runtime = self._sessions.get(session_id)
        if runtime is None:
            return {"ok": False, "reason": "session not registered"}
        client = runtime.client
        if client is None:
            return {"ok": False, "reason": "no active Claude SDK client"}
        try:
            await client.stop_task(task_id)
        except Exception as exc:
            logger.debug(
                "stop_task failed session_id={} task_id={}",
                session_id,
                task_id,
                exc_info=True,
            )
            return {"ok": False, "reason": str(exc) or "stop_task failed"}
        return {"ok": True}

    async def reconnect_mcp_server(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _required(params, "sessionId")
        server_name = _required(params, "serverName")
        runtime = self._sessions.get(session_id)
        if runtime is None:
            return {"ok": False, "reason": "session not registered"}
        client = runtime.client
        if client is None:
            return {"ok": False, "reason": "no active Claude SDK client"}
        try:
            await client.reconnect_mcp_server(server_name)
        except Exception as exc:
            logger.debug(
                "reconnect_mcp_server failed session_id={} server_name={}",
                session_id,
                server_name,
                exc_info=True,
            )
            return {"ok": False, "reason": str(exc) or "reconnect_mcp_server failed"}
        return {"ok": True}

    async def toggle_mcp_server(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _required(params, "sessionId")
        server_name = _required(params, "serverName")
        enabled = bool(params.get("enabled", True))
        runtime = self._sessions.get(session_id)
        if runtime is None:
            return {"ok": False, "reason": "session not registered"}
        client = runtime.client
        if client is None:
            return {"ok": False, "reason": "no active Claude SDK client"}
        try:
            await client.toggle_mcp_server(server_name, enabled)
        except Exception as exc:
            logger.debug(
                "toggle_mcp_server failed session_id={} server_name={} enabled={}",
                session_id,
                server_name,
                enabled,
                exc_info=True,
            )
            return {"ok": False, "reason": str(exc) or "toggle_mcp_server failed"}
        return {"ok": True}

    async def get_context_usage(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _required(params, "sessionId")
        runtime = self._sessions.get(session_id)
        if runtime is None:
            return {"ok": False, "reason": "session not registered"}
        client = runtime.client
        if client is None:
            return {"ok": False, "reason": "no active Claude SDK client"}
        getter = getattr(client, "get_context_usage", None)
        if not callable(getter):
            return {"ok": False, "reason": "get_context_usage not available"}
        try:
            raw = await getter()
            usage = _context_usage_from_response(raw)
            return {"ok": True, "usage": usage}
        except Exception as exc:
            logger.debug(
                "get_context_usage failed session_id={}",
                session_id,
                exc_info=True,
            )
            return {"ok": False, "reason": str(exc) or "get_context_usage failed"}

    async def _apply_runtime_setting(
        self,
        params: dict[str, Any],
        *,
        method_name: str,
        value: str | None,
        allow_none: bool,
    ) -> dict[str, Any]:
        runtime = self._sessions.get(_required(params, "sessionId"))
        if runtime is None:
            return {"applied": False, "reason": "session not registered"}
        client = runtime.client
        if client is None:
            return {"applied": False, "reason": "no active Claude SDK client"}
        setter = getattr(client, method_name, None)
        if not callable(setter):
            return {"applied": False, "reason": f"client does not support {method_name}"}
        if value is None and not allow_none:
            return {"applied": False, "reason": "value is required"}
        try:
            await setter(value)
        except Exception as exc:
            logger.debug(
                "claude sdk {} failed session_id={} external_session_id={}",
                method_name,
                runtime.session_id,
                runtime.external_session_id,
                exc_info=True,
            )
            return {"applied": False, "reason": str(exc) or method_name + " failed"}
        return {"applied": True, "value": value}

    async def resolve_approval(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = _required(params, "sessionId")
        approval_id = _required(params, "approvalId")
        status = _required(params, "status")
        runtime = self._sessions.get(session_id)
        if runtime is None:
            return {"resolved": False, "reason": "session not registered"}
        pending = runtime.pending_approvals.get(approval_id)
        if pending is None:
            return {"resolved": False, "reason": "approval not pending"}
        selections = params.get("selections")
        if selections and pending.tool_name == "AskUserQuestion":
            # Map the user's selections to the `answers` field the CLI expects:
            # {question_text: answer_string | [answer_string, ...]}. Multi-select
            # answers stay as a list; the CLI joins them with ", " itself.
            pending.answers = _selections_to_answers(selections)
        if not pending.future.done():
            pending.future.set_result(status)
        return {"resolved": True}

    async def get_mcp_status(self, params: dict[str, Any]) -> dict[str, Any]:
        # Query the live SDK client for its current MCP server list. This is a
        # per-call snapshot (SDK ClaudeSDKClient.get_mcp_status()); we don't
        # subscribe to change events. "Nothing to report" is expressed as an
        # empty `mcpServers` list rather than an error so the client can render
        # a stable "no MCP servers" state whether the session is idle, the SDK
        # is too old, or no servers were configured — same shape either way.
        # Callers include the SDK's raw response verbatim (see design doc:
        # "return the SDK response verbatim, don't remap") minus non-dict
        # payloads which we normalize to an empty list.
        session_id = _optional_string(params.get("sessionId"))
        if not session_id:
            return {"mcpServers": []}
        runtime = self._sessions.get(session_id)
        if runtime is None or runtime.client is None:
            return {"mcpServers": []}
        getter = getattr(runtime.client, "get_mcp_status", None)
        if not callable(getter):
            return {"mcpServers": []}
        try:
            raw = await getter()
        except Exception:
            logger.debug(
                "claude sdk get_mcp_status failed session_id={} external_session_id={}",
                runtime.session_id,
                runtime.external_session_id,
                exc_info=True,
            )
            return {"mcpServers": []}
        if isinstance(raw, dict):
            servers = raw.get("mcpServers")
            return {"mcpServers": servers if isinstance(servers, list) else []}
        return {"mcpServers": []}

    async def rename_session(self, params: dict[str, Any]) -> dict[str, Any]:
        external_session_id = _optional_string(params.get("externalSessionId"))
        title = _optional_string(params.get("title"))
        if not external_session_id or not title:
            return {"ok": False, "reason": "externalSessionId and title required"}
        cwd = _optional_string(params.get("cwd"))
        sdk = self._load_sdk()
        rename_fn = getattr(sdk, "rename_session", None)
        if not callable(rename_fn):
            return {"ok": False, "reason": "sdk does not support rename_session"}
        try:
            if cwd:
                rename_fn(external_session_id, title, directory=cwd)
            else:
                rename_fn(external_session_id, title)
        except Exception:
            logger.debug(
                "sdk rename_session failed external_session_id={} title={}",
                external_session_id,
                title,
                exc_info=True,
            )
            return {"ok": False, "reason": "rename_session failed"}
        return {"ok": True}

    async def delete_session(self, params: dict[str, Any]) -> dict[str, Any]:
        external_session_id = _optional_string(params.get("externalSessionId"))
        if not external_session_id:
            return {"ok": False, "reason": "externalSessionId required"}
        cwd = _optional_string(params.get("cwd"))
        sdk = self._load_sdk()
        delete_fn = getattr(sdk, "delete_session", None)
        if not callable(delete_fn):
            return {"ok": False, "reason": "sdk does not support delete_session"}
        try:
            if cwd:
                delete_fn(external_session_id, directory=cwd)
            else:
                delete_fn(external_session_id)
        except Exception:
            logger.debug(
                "sdk delete_session failed external_session_id={}",
                external_session_id,
                exc_info=True,
            )
            return {"ok": False, "reason": "delete_session failed"}
        return {"ok": True}

    async def fork_session(self, params: dict[str, Any]) -> dict[str, Any]:
        external_session_id = _optional_string(params.get("externalSessionId"))
        if not external_session_id:
            return {"ok": False, "reason": "externalSessionId required"}
        cwd = _optional_string(params.get("cwd"))
        up_to_message_id = _optional_string(params.get("upToMessageId"))
        title = _optional_string(params.get("title"))
        sdk = self._load_sdk()
        fork_fn = getattr(sdk, "fork_session", None)
        if not callable(fork_fn):
            return {"ok": False, "reason": "sdk does not support fork_session"}
        try:
            kwargs: dict[str, Any] = {}
            if cwd:
                kwargs["directory"] = cwd
            if up_to_message_id:
                kwargs["up_to_message_id"] = up_to_message_id
            if title:
                kwargs["title"] = title
            result = fork_fn(external_session_id, **kwargs)
            return {"ok": True, "sessionId": result.session_id}
        except Exception:
            logger.debug(
                "sdk fork_session failed external_session_id={}",
                external_session_id,
                exc_info=True,
            )
            return {"ok": False, "reason": "fork_session failed"}

    async def tag_session(self, params: dict[str, Any]) -> dict[str, Any]:
        external_session_id = _optional_string(params.get("externalSessionId"))
        if not external_session_id:
            return {"ok": False, "reason": "externalSessionId required"}
        # tag=None clears the tag; omitting the key entirely is treated as clear too
        tag: str | None = params.get("tag")  # may be None (explicit clear) or str
        cwd = _optional_string(params.get("cwd"))
        sdk = self._load_sdk()
        tag_fn = getattr(sdk, "tag_session", None)
        if not callable(tag_fn):
            return {"ok": False, "reason": "sdk does not support tag_session"}
        try:
            if cwd:
                tag_fn(external_session_id, tag, directory=cwd)
            else:
                tag_fn(external_session_id, tag)
        except Exception:
            logger.debug(
                "sdk tag_session failed external_session_id={}",
                external_session_id,
                exc_info=True,
            )
            return {"ok": False, "reason": "tag_session failed"}
        return {"ok": True}

    def _runtime_for(self, session_id: str, params: dict[str, Any]) -> _SdkSessionRuntime:
        runtime = self._sessions.get(session_id)
        if runtime is None:
            runtime = _SdkSessionRuntime(
                session_id=session_id,
                cwd=_optional_string(params.get("cwd")),
                external_session_id=_optional_string(params.get("externalSessionId")),
            )
            self._sessions[session_id] = runtime
        if params.get("cwd"):
            runtime.cwd = _optional_string(params.get("cwd"))
        if params.get("externalSessionId"):
            runtime.external_session_id = _optional_string(params.get("externalSessionId"))
        return runtime

    async def _drive_turn(
        self,
        *,
        runtime: _SdkSessionRuntime,
        params: dict[str, Any],
        content: str,
        turn_id: str,
    ) -> None:
        stream_finished = False
        try:
            runtime.stderr_lines.clear()
            await self._emit_item(runtime.session_id, _turn_start_item(runtime, turn_id))
            client = self._client(runtime, params)
            # The prior turn's client is kept alive between turns so set_model /
            # set_permission_mode / get_mcp_status can reach a live client. When a
            # new turn supersedes it, tear the old one down first so its CLI
            # subprocess/transport isn't orphaned (construction above spawns no
            # process; connect() below does, so this keeps at most one live).
            previous_client = runtime.client
            runtime.client = client
            if previous_client is not None and previous_client is not client:
                await _disconnect_client(previous_client)
            await _maybe_await(getattr(client, "connect", None))
            runtime_content = await self._materialize_runtime_content(
                content=content,
                attachments=params.get("attachments"),
                cwd=runtime.cwd,
                session_id=runtime.session_id,
            )
            await client.query(_prompt_stream(runtime_content))
            await self._receive_response(runtime, client, turn_id)
            # The client is still connected here, so a get_context_usage() RPC
            # (the /context data: totalTokens/maxTokens/percentage/autocompact)
            # is available. It never lands in the transcript, so this is the
            # only place to capture it; failures are non-fatal.
            await self._capture_context_usage(runtime, client)
            stream_finished = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            stderr = _stderr_excerpt(runtime.stderr_lines)
            logger.exception(
                "claude sdk turn failed session_id={} turn_id={} cwd={} external_session_id={} "
                "model={} effort={} permission_mode={} cli_path={} stderr={}",
                runtime.session_id,
                turn_id,
                runtime.cwd,
                runtime.external_session_id,
                _optional_string(params.get("model")),
                _optional_string(params.get("effort")),
                _optional_string(params.get("permissionMode")),
                self.claude_bin,
                stderr or "<empty>",
            )
            stop_reason = _failure_message(exc, stderr)
            await self._finalize_live_stream_items(runtime, turn_id, status="failed")
            await self._finalize_live_tool_items(runtime, turn_id, status="failed")
            await self._emit_item(
                runtime.session_id,
                _turn_end_item(
                    runtime,
                    turn_id,
                    status="failed",
                    result="failed",
                    stop_reason=stop_reason,
                ),
            )
            if self.notification_sink is not None:
                await self.notification_sink(
                    "runtime.error",
                    {
                        "sessionId": runtime.session_id,
                        "runtime": "claude",
                        "message": stop_reason,
                        "stderr": stderr,
                    },
                )
        finally:
            if stream_finished:
                await self._mark_history_consumed(runtime)
            if runtime.active_turn_id == turn_id:
                runtime.active_turn_id = None
                runtime.active_task = None
                runtime.current_client_message_id = None
                runtime.current_content = None
                runtime.current_attachments = None
                runtime.emitted_user_message = False
            # Resolve any still-pending approval futures before dropping them, or
            # a _can_use_tool coroutine still awaiting one (e.g. the SDK ended the
            # stream while the future was outstanding) would hang forever. Match
            # interrupt_turn's "cancelled" resolution.
            for _pending in runtime.pending_approvals.values():
                if not _pending.future.done():
                    _pending.future.set_result("cancelled")
            runtime.pending_approvals.clear()
            self._prepare_history_adapter()
            await self._emit_session_update(runtime, status="idle")

    async def _receive_response(self, runtime: _SdkSessionRuntime, client: Any, turn_id: str) -> None:
        receive_response = getattr(client, "receive_response", None)
        if not callable(receive_response):
            raise ClaudeSdkAdapterError("ClaudeSDKClient does not expose receive_response()")
        saw_result = False
        emitted_live_content = False
        buffered_messages: list[Any] = []
        async for message in receive_response():
            if _is_stream_event(message):
                session_id = _optional_string(_extract_attr(message, "session_id", "sessionId"))
                if session_id:
                    runtime.external_session_id = session_id
                    self._prepare_history_adapter()
                    await self._emit_session_update(runtime, status="running")
                if runtime.external_session_id is None:
                    buffered_messages.append(message)
                    continue
                await self._emit_pending_user_message(runtime, turn_id)
                emitted_live_content = await self._emit_stream_event(runtime, turn_id, message) or emitted_live_content
                continue
            if _is_result_message(message):
                saw_result = True
                session_id = _extract_attr(message, "session_id", "sessionId")
                if isinstance(session_id, str) and session_id:
                    runtime.external_session_id = session_id
                    self._prepare_history_adapter()
                    await self._emit_session_update(runtime, status="running")
                await self._emit_pending_user_message(runtime, turn_id)
                for buffered in buffered_messages:
                    if _is_stream_event(buffered):
                        emitted_live_content = await self._emit_stream_event(runtime, turn_id, buffered) or emitted_live_content
                    elif _is_task_progress_message(buffered):
                        emitted_live_content = await self._emit_task_progress(runtime, turn_id, buffered) or emitted_live_content
                    elif _is_rate_limit_message(buffered):
                        await self._capture_rate_limit(runtime, buffered)
                    elif _is_hook_event_message(buffered):
                        emitted_live_content = await self._emit_hook_event(runtime, turn_id, buffered) or emitted_live_content
                    else:
                        emitted_live_content = await self._emit_sdk_message(runtime, turn_id, buffered) or emitted_live_content
                if not emitted_live_content:
                    emitted_live_content = await self._emit_result_message(runtime, turn_id, message) or emitted_live_content
                subtype = _optional_string(_extract_attr(message, "subtype"))
                status = "interrupted" if runtime.interrupted else ("failed" if subtype in {"error", "failed"} else "done")
                result = "interrupted" if runtime.interrupted else ("failed" if status == "failed" else "completed")
                await self._finalize_live_stream_items(runtime, turn_id, status=status)
                await self._finalize_live_tool_items(runtime, turn_id, status=status)
                await self._emit_item(
                    runtime.session_id,
                    _turn_end_item(
                        runtime,
                        turn_id,
                        status=status,
                        result=result,
                        stop_reason=subtype or result,
                        usage=_turn_usage_from_result(message),
                    ),
                )
                break
            if _is_task_progress_message(message):
                if runtime.external_session_id is None:
                    buffered_messages.append(message)
                    continue
                await self._emit_pending_user_message(runtime, turn_id)
                emitted_live_content = await self._emit_task_progress(runtime, turn_id, message) or emitted_live_content
                continue
            if _is_rate_limit_message(message):
                # Rate-limit state change. Snapshot it onto the runtime and push a
                # session.updated so clients can warn about quota. It carries no
                # timeline content, so it never counts as emitted_live_content.
                await self._capture_rate_limit(runtime, message)
                continue
            if _is_hook_event_message(message):
                # Hook lifecycle event (include_hook_events). Only Notification
                # surfaces a timeline item; every other hook is swallowed inside
                # _emit_hook_event. Never route it to _emit_sdk_message.
                if runtime.external_session_id is None:
                    buffered_messages.append(message)
                    continue
                await self._emit_pending_user_message(runtime, turn_id)
                emitted_live_content = await self._emit_hook_event(runtime, turn_id, message) or emitted_live_content
                continue
            if runtime.external_session_id is None:
                buffered_messages.append(message)
                continue
            await self._emit_pending_user_message(runtime, turn_id)
            emitted_live_content = await self._emit_sdk_message(runtime, turn_id, message) or emitted_live_content
        if not saw_result:
            status = "interrupted" if runtime.interrupted else "done"
            await self._emit_pending_user_message(runtime, turn_id)
            for buffered in buffered_messages:
                if _is_stream_event(buffered):
                    await self._emit_stream_event(runtime, turn_id, buffered)
                elif _is_task_progress_message(buffered):
                    await self._emit_task_progress(runtime, turn_id, buffered)
                elif _is_rate_limit_message(buffered):
                    await self._capture_rate_limit(runtime, buffered)
                elif _is_hook_event_message(buffered):
                    await self._emit_hook_event(runtime, turn_id, buffered)
                else:
                    await self._emit_sdk_message(runtime, turn_id, buffered)
            await self._finalize_live_stream_items(runtime, turn_id, status=status)
            await self._finalize_live_tool_items(runtime, turn_id, status=status)
            await self._emit_item(
                runtime.session_id,
                _turn_end_item(
                    runtime,
                    turn_id,
                    status=status,
                    result="interrupted" if runtime.interrupted else "completed",
                    stop_reason="interrupted" if runtime.interrupted else "completed",
                ),
            )

    async def _emit_sdk_message(self, runtime: _SdkSessionRuntime, turn_id: str, message: Any) -> bool:
        role = _message_role(message)
        raw = _sdk_message_to_raw(
            message,
            runtime.external_session_id,
        )
        if raw is not None:
            return await self._emit_normalized(
                runtime.session_id,
                turn_id,
                raw,
                streaming=role == "assistant",
            )
        return False

    async def _emit_stream_event(self, runtime: _SdkSessionRuntime, turn_id: str, message: Any) -> bool:
        raw = _stream_event_to_raw(runtime, turn_id, message)
        if raw is not None:
            return await self._emit_normalized(runtime.session_id, turn_id, raw, streaming=True)
        return False

    async def _emit_result_message(self, runtime: _SdkSessionRuntime, turn_id: str, message: Any) -> bool:
        raw = _result_message_to_raw(message, runtime.external_session_id)
        if raw is not None:
            return await self._emit_normalized(runtime.session_id, turn_id, raw)
        return False

    async def _emit_task_progress(self, runtime: _SdkSessionRuntime, turn_id: str, message: Any) -> bool:
        # Sub-agent (Task/Agent) progress is a real-time-only signal: the SDK
        # emits TaskStarted/TaskUpdated/TaskNotification system messages while a
        # sub-agent runs, but they are never written to the transcript JSONL, so
        # the history-replay path never sees them. Rather than route them through
        # the transcript-shared normalizer/reducer (which would desync live vs
        # replay), we merge them straight into the parent Agent tool card's
        # content.subagent and re-upsert that card. The parent is resolved via
        # the task's tool_use_id (present on Started/Notification) or, for a bare
        # TaskUpdated (task_id only), the task_id -> tool_use_id map recorded from
        # the Started message.
        progress = _task_progress_from_message(message)
        if progress is None:
            return False
        task_id = progress["taskId"]
        tool_use_id = progress.get("toolUseId")
        if tool_use_id:
            runtime.subagent_task_to_tool[task_id] = tool_use_id
        else:
            tool_use_id = runtime.subagent_task_to_tool.get(task_id)
        if not tool_use_id:
            # A TaskUpdated arriving before we ever saw its Started message has no
            # anchor to attach to; drop it rather than orphaning a card.
            return False
        card_id = ClaudeTimelineIdentity.tool_call(
            session_id=runtime.session_id,
            claude_session_id=runtime.external_session_id or "unknown",
            tool_use_id=tool_use_id,
        )
        existing = runtime.live_tool_items.get(card_id)
        if existing is None:
            # The parent Agent tool card streams in as its own tool_use block; if
            # it hasn't landed yet, stash the progress so it can be folded in when
            # the card is first prepared (see _prepare_live_tool_item).
            runtime.subagent_progress[tool_use_id] = _merge_subagent_progress(
                runtime.subagent_progress.get(tool_use_id), progress
            )
            return False
        merged = _merge_subagent_progress(
            (existing.get("content") or {}).get("subagent") if isinstance(existing.get("content"), dict) else None,
            progress,
        )
        runtime.subagent_progress[tool_use_id] = merged
        content = dict(existing.get("content") if isinstance(existing.get("content"), dict) else {})
        content["subagent"] = merged
        updated = dict(existing)
        updated["content"] = content
        updated["revision"] = int(existing.get("revision") or 1) + 1
        updated["contentHash"] = _hash_content(content)
        updated["updatedAt"] = utc_now()
        runtime.live_tool_items[card_id] = updated
        await self._emit_item(runtime.session_id, updated)
        return True

    async def _emit_hook_event(self, runtime: _SdkSessionRuntime, turn_id: str, message: Any) -> bool:
        # include_hook_events streams every hook lifecycle event back as a
        # HookEventMessage. We surface only Notification (a CLI-initiated
        # message asking for the user's attention — there is no other channel
        # for it); every other hook is already covered elsewhere (tool lifecycle
        # by tool_result, sub-agent by task progress, compaction by the compact
        # boundary) so we swallow them here rather than let them fall through to
        # _emit_sdk_message and pollute the timeline. Fires on hook_response so
        # we act once per hook, not on both started and response.
        notification = _notification_from_hook_message(message)
        if notification is None:
            return False
        content: dict[str, Any] = {"kind": "notification", "message": notification["message"]}
        if notification.get("title"):
            content["title"] = notification["title"]
        if notification.get("notificationType"):
            content["notificationType"] = notification["notificationType"]
        item = _timeline_item(
            id=f"{turn_id}:notification:{_short_hash([notification['message'], notification.get('title'), runtime.next_order_seq])}",
            session_id=runtime.session_id,
            turn_id=turn_id,
            item_type="system",
            status="done",
            role="system",
            content=content,
            external_session_id=runtime.external_session_id,
            source_item_type="hook_notification",
            derived_key="notification",
            order_seq=_next_order(runtime),
        )
        await self._emit_item(runtime.session_id, item)
        return True

    async def _emit_normalized(
        self,
        session_id: str,
        turn_id: str,
        raw: dict[str, Any],
        *,
        streaming: bool = False,
    ) -> bool:
        reducer = ClaudeTimelineReducer()
        events = ClaudeLiveNormalizer().normalize([raw])
        runtime = self._sessions.get(session_id)
        if runtime is not None:
            events = _filter_live_task_events(runtime, events)
        emitted = False
        for item in reducer.reduce(session_id=session_id, turn_id=turn_id, events=events):
            dumped = dict(item)
            if runtime is not None:
                if streaming and (_is_streaming_assistant_message(dumped) or _is_streaming_reasoning_item(dumped)):
                    prepared = _prepare_live_stream_item(runtime, dumped)
                    if prepared is None:
                        continue
                    dumped = prepared
                elif _is_streaming_assistant_message(dumped) or _is_streaming_reasoning_item(dumped):
                    prepared = _prepare_live_stream_final_item(runtime, dumped)
                    if prepared is not None:
                        dumped = prepared
                    else:
                        dumped["orderSeq"] = _next_order(runtime)
                elif _is_tool_item(dumped):
                    prepared = _prepare_live_tool_item(runtime, dumped)
                    if prepared is None:
                        continue
                    dumped = prepared
                else:
                    dumped["orderSeq"] = _next_order(runtime)
            await self._emit_item(session_id, dumped)
            emitted = True
        return emitted

    async def _finalize_live_stream_items(
        self,
        runtime: _SdkSessionRuntime,
        turn_id: str,
        *,
        status: str,
    ) -> None:
        if not runtime.live_stream_items:
            return
        completed_at = utc_now()
        for item_id, item in list(runtime.live_stream_items.items()):
            if item.get("turnId") != turn_id:
                continue
            if item.get("status") == status and item.get("completedAt"):
                continue
            finalized = dict(item)
            finalized["status"] = status
            finalized["revision"] = int(finalized.get("revision") or 1) + 1
            finalized["updatedAt"] = completed_at
            finalized["completedAt"] = completed_at
            runtime.live_stream_items[item_id] = finalized
            await self._emit_item(runtime.session_id, finalized)

    async def _finalize_live_tool_items(
        self,
        runtime: _SdkSessionRuntime,
        turn_id: str,
        *,
        status: str,
    ) -> None:
        # Tool items (Bash, Edit, Task/sub-agent, ...) start life as "running"
        # on their tool_use and only flip to a terminal status when their
        # tool_result arrives. If the turn ends first -- interrupted, failed, or
        # the sub-agent/process dying before returning a result -- that result
        # never comes, so the item is stranded at "running" forever and the UI
        # spins indefinitely. When the turn wraps up we sweep this turn's tool
        # items and force any still-open one to the turn's terminal status.
        # Items that already reached a terminal state are left untouched so a
        # normally-completed tool is never rewritten.
        if not runtime.live_tool_items:
            return
        terminal = {"done", "failed", "interrupted", "cancelled"}
        completed_at = utc_now()
        for item_id, item in list(runtime.live_tool_items.items()):
            if item.get("turnId") != turn_id:
                continue
            if item.get("status") in terminal:
                continue
            finalized = dict(item)
            finalized["status"] = status
            finalized["revision"] = int(finalized.get("revision") or 1) + 1
            finalized["updatedAt"] = completed_at
            finalized["completedAt"] = completed_at
            runtime.live_tool_items[item_id] = finalized
            await self._emit_item(runtime.session_id, finalized)

    async def _emit_pending_user_message(self, runtime: _SdkSessionRuntime, turn_id: str) -> None:
        if runtime.emitted_user_message:
            return
        if not runtime.external_session_id or runtime.current_content is None:
            return
        events = [
            NormalizedClaudeEvent(
                claudeSessionId=runtime.external_session_id,
                sourceEventId=f"{turn_id}:user",
                messageId=f"{turn_id}:user",
                role="user",
                blockIndex=0,
                blockType="text",
                text=runtime.current_content,
                timestamp=utc_now(),
                clientMessageId=runtime.current_client_message_id,
                attachments=runtime.current_attachments,
            )
        ]
        for item in ClaudeTimelineReducer().reduce(
            session_id=runtime.session_id,
            turn_id=turn_id,
            events=events,
        ):
            item["orderSeq"] = _next_order(runtime)
            await self._emit_item(runtime.session_id, item)
        runtime.emitted_user_message = True

    async def _emit_item(self, session_id: str, item: dict[str, Any]) -> None:
        if self.notification_sink is None:
            return
        await self.notification_sink("timeline.itemUpsert", {"sessionId": session_id, "item": item})

    async def _emit_session_update(self, runtime: _SdkSessionRuntime, *, status: str) -> None:
        if self.notification_sink is None:
            return
        payload: dict[str, Any] = {
            "sessionId": runtime.session_id,
            "runtime": "claude",
            "externalSessionId": runtime.external_session_id,
            "status": status,
            "cwd": runtime.cwd,
            "lastSyncedAt": utc_now(),
        }
        if runtime.context_usage is not None:
            payload["contextUsage"] = runtime.context_usage
        if runtime.rate_limit is not None:
            payload["rateLimit"] = runtime.rate_limit
        if runtime.pending_permission_mode is not None:
            # An approved ExitPlanMode: tell the server to persist the execution
            # mode as the session override so the next turn leaves plan mode.
            # Cleared once emitted so it rides exactly one session.updated.
            payload["permissionMode"] = runtime.pending_permission_mode
            runtime.pending_permission_mode = None
        await self.notification_sink("session.updated", payload)

    async def _capture_rate_limit(self, runtime: _SdkSessionRuntime, message: Any) -> None:
        # A RateLimitEvent snapshots the CLI's throttling state. Store the latest
        # snapshot on the runtime and push a session.updated so clients can react.
        # We always keep the newest snapshot (including a plain "allowed") rather
        # than clearing to None: the session.updated -> DB write path only writes
        # the column when rateLimit is present, so a clear must be expressed as a
        # status="allowed" snapshot the client reads, not a dropped field. The
        # client hides the warning when status is "allowed".
        snapshot = _rate_limit_from_message(message)
        if snapshot is None:
            return
        # Skip a redundant "allowed" when we never had a warning to clear, so the
        # steady state doesn't emit a rateLimit field the client would ignore.
        if snapshot.get("status") == "allowed" and runtime.rate_limit is None:
            return
        runtime.rate_limit = snapshot
        await self._emit_session_update(runtime, status="running")

    async def _capture_context_usage(self, runtime: _SdkSessionRuntime, client: Any) -> None:
        # get_context_usage() is a runtime RPC available only while the client
        # is connected; it mirrors the CLI /context view. We snapshot it after
        # each turn onto the runtime so the next session.updated carries it. Any
        # failure (older CLI without the RPC, disconnect race) is swallowed —
        # the gauge is a nicety, not correctness-critical.
        getter = getattr(client, "get_context_usage", None)
        if not callable(getter):
            return
        try:
            raw = await getter()
        except Exception:
            logger.debug(
                "claude sdk get_context_usage failed session_id={} external_session_id={}",
                runtime.session_id,
                runtime.external_session_id,
                exc_info=True,
            )
            return
        usage = _context_usage_from_response(raw)
        if usage is not None:
            runtime.context_usage = usage

    async def _mark_history_consumed(self, runtime: _SdkSessionRuntime) -> None:
        try:
            self._prepare_history_adapter()
            await self.history_adapter.mark_session_consumed(
                connector_id=runtime.connector_id,
                external_session_id=runtime.external_session_id,
                cwd=runtime.cwd,
            )
        except Exception:
            logger.exception(
                "claude sdk history consumed marker failed session_id={} external_session_id={}",
                runtime.session_id,
                runtime.external_session_id,
            )

    async def _sync_current_history_snapshot(self, runtime: _SdkSessionRuntime) -> None:
        if runtime.external_session_id is None:
            return
        try:
            self._prepare_history_adapter()
            result = await self.history_adapter.sync_session(
                {
                    "sessionId": runtime.session_id,
                    "externalSessionId": runtime.external_session_id,
                    "cwd": runtime.cwd,
                    "pendingClientMessages": _pending_client_messages(runtime),
                }
            )
        except Exception:
            logger.exception(
                "claude sdk history snapshot failed session_id={} external_session_id={}",
                runtime.session_id,
                runtime.external_session_id,
            )
            return
        notifications = result.get("backendNotifications") if isinstance(result, dict) else None
        if self.notification_sink is None or not isinstance(notifications, list):
            return
        for notification in notifications:
            if not isinstance(notification, dict):
                continue
            method = notification.get("method")
            params = notification.get("params")
            if isinstance(method, str) and isinstance(params, dict):
                await self.notification_sink(method, params)

    def _prepare_history_adapter(self) -> None:
        self.history_adapter.sdk_module = self.sdk_module

    def _client(self, runtime: _SdkSessionRuntime, params: dict[str, Any]) -> Any:
        sdk = self._load_sdk()
        options = sdk.ClaudeAgentOptions(**self._options_kwargs(sdk, runtime, params))
        client_cls = sdk.ClaudeSDKClient
        try:
            return client_cls(options=options)
        except TypeError:
            return client_cls(options)

    def _options_kwargs(self, sdk: Any, runtime: _SdkSessionRuntime, params: dict[str, Any]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "include_partial_messages": True,
            "can_use_tool": self._can_use_tool,
            "stderr": lambda line: _record_stderr(runtime, line),
            # Stream hook lifecycle events into the message loop as
            # HookEventMessage. We only act on Notification (a CLI-initiated
            # system message with no other channel); every other hook is
            # dropped in _receive_response (see _is_hook_event_message). This
            # does not replace the PreToolUse decision callback below — that
            # stays the permission gate; include_hook_events is purely
            # observational.
            "include_hook_events": True,
            # Opus 4.7+ defaults display="omitted" which returns only a
            # signature without the thinking text, making reasoning cards
            # appear empty. Force "summarized" so the full text is always
            # available regardless of model or SDK version changes.
            "thinking": {"type": "adaptive", "display": "summarized"},
        }
        if runtime.cwd:
            kwargs["cwd"] = runtime.cwd
        if runtime.external_session_id:
            kwargs["resume"] = runtime.external_session_id
        if self.claude_target is not None:
            kwargs["cli_path"] = self.claude_target.path
        for param_key, option_key in (
            ("permissionMode", "permission_mode"),
            ("effort", "effort"),
        ):
            value = _optional_string(params.get(param_key))
            if value:
                kwargs[option_key] = value
        model = _optional_string(params.get("model"))
        if model:
            # [1M] suffix signals the 1M-context beta; strip it and inject betas.
            if model.endswith("[1M]"):
                kwargs["model"] = model[:-4]
                kwargs["betas"] = ["context-1m-2025-08-07"]
            else:
                kwargs["model"] = model
        max_turns = _positive_int(params.get("maxTurns"))
        if max_turns is not None:
            kwargs["max_turns"] = max_turns
        # MCP server configs come from a local file (mcp.json) via a provider so
        # tests can inject in-memory configs. The provider is called every turn
        # so hand-edits to mcp.json take effect on the next turn without
        # restarting the connector. When the provider returns an empty dict
        # (missing file, invalid JSON, no configured servers) we skip both keys
        # so behavior is bit-identical to pre-MCP: zero regression is a hard
        # acceptance criterion, and `strict_mcp_config=True` on an empty dict
        # would disable the SDK's own default MCP discovery path — a change of
        # semantics we don't want when the user hasn't opted in.
        mcp_servers = self._load_mcp_servers()
        if mcp_servers:
            kwargs["mcp_servers"] = dict(mcp_servers)
            kwargs["strict_mcp_config"] = True
        hook_matcher = _optional_attr(sdk, "HookMatcher", "types.HookMatcher")
        if hook_matcher is not None:
            async def _keep_permission_stream_open(_input_data: Any, _tool_use_id: Any = None, _context: Any = None) -> dict[str, bool]:
                return {"continue_": True}

            kwargs["hooks"] = {"PreToolUse": [hook_matcher(matcher=None, hooks=[_keep_permission_stream_open])]}
        return kwargs

    async def _can_use_tool(self, tool_name: str, input_data: dict[str, Any], context: Any = None) -> Any:
        sdk = self._load_sdk()
        context_session_id = _optional_string(_extract_attr(context, "session_id", "sessionId"))
        runtime = self._runtime_from_context(context_session_id)
        if runtime is None:
            return _permission_deny(sdk, "Session is not registered")
        # "Approve for session": if this exact tool_name + canonicalized input was
        # previously approved_for_session, auto-allow without re-prompting. The key
        # is parameter-exact (see _approval_rule_key) so approving `Read /a.txt`
        # never silently allows `Read /b.txt` or `Bash rm -rf /`.
        rule_key = _approval_rule_key(tool_name, input_data)
        if rule_key in runtime.session_approved_rules and not runtime.interrupted:
            return _permission_allow(sdk, input_data)
        approval_id = _approval_id(runtime.session_id, runtime.active_turn_id, tool_name, input_data)
        # Two identical tool calls in one turn (same tool_name + input) hash to
        # the same id. Without disambiguation the second registration would
        # overwrite the first's pending future, orphaning it: the first
        # _can_use_tool would await forever (interrupt_turn can't rescue a future
        # that's no longer in the dict). Suffix on collision so each concurrent
        # prompt keeps its own resolvable id; the common no-collision path keeps
        # the deterministic id unchanged.
        if approval_id in runtime.pending_approvals:
            suffix = 2
            while f"{approval_id}_{suffix}" in runtime.pending_approvals:
                suffix += 1
            approval_id = f"{approval_id}_{suffix}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        runtime.pending_approvals[approval_id] = _PendingSdkApproval(
            approval_id, future, input_data, tool_name=tool_name
        )
        if self.notification_sink is not None:
            await self.notification_sink(
                "approval.requested",
                _approval_payload(
                    approval_id=approval_id,
                    runtime=runtime,
                    tool_name=tool_name,
                    input_data=input_data,
                ),
            )
        status = await future
        pending = runtime.pending_approvals.pop(approval_id, None)
        if status in {"approved", "approved_for_session"} and not runtime.interrupted:
            if status == "approved_for_session":
                # Remember this exact tool_name + input for the rest of the session
                # so identical calls auto-allow. Cleared with the runtime on a new
                # session / restart, so stale grants never leak across sessions.
                runtime.session_approved_rules.add(rule_key)
            if tool_name == "ExitPlanMode":
                # ExitPlanMode carries the target permissionMode to switch to after
                # the plan turn ends (e.g. "acceptEdits"). Store it so the next
                # session.updated notification carries permissionMode and the server
                # persists it as the override — ensuring subsequent turns run in
                # execute mode rather than re-entering plan.
                exit_mode = _optional_string(input_data.get("permissionMode"))
                runtime.pending_permission_mode = exit_mode or "acceptEdits"
            resolved_input = input_data
            if pending is not None and pending.answers:
                # AskUserQuestion: merge the user's selections into the tool input
                # under `answers` (question text -> answer string). The CLI reads
                # this via the permission component and surfaces it to the model as
                # "Your questions have been answered: ..." instead of the default
                # "The user did not answer the questions."
                resolved_input = {**input_data, "answers": pending.answers}
            return _permission_allow(sdk, resolved_input)
        return _permission_deny(sdk, "User denied or interrupted this action")

    def _runtime_from_context(self, context_session_id: str | None) -> _SdkSessionRuntime | None:
        if context_session_id:
            for runtime in self._sessions.values():
                if runtime.external_session_id == context_session_id:
                    return runtime
        for runtime in self._sessions.values():
            if runtime.active_turn_id:
                return runtime
        return None

    def _load_sdk(self) -> Any:
        if self.sdk_module is not None:
            return self.sdk_module
        try:
            import claude_agent_sdk  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise ClaudeSdkAdapterError("claude-agent-sdk is not installed") from exc
        return claude_agent_sdk

    def _load_mcp_servers(self) -> dict[str, dict[str, Any]]:
        # Resolve the MCP server dict for the next turn. Injected provider wins
        # (tests use this); default falls back to the on-disk `mcp.json` loader.
        # Any provider failure degrades to "no MCP" rather than failing the turn:
        # a broken config file must never be able to knock the whole runtime out.
        provider = self.mcp_config_provider
        if provider is None:
            try:
                return load_mcp_servers()
            except Exception:
                logger.exception("loading mcp.json failed; falling back to no MCP servers")
                return {}
        try:
            servers = provider()
        except Exception:
            logger.exception("mcp_config_provider raised; falling back to no MCP servers")
            return {}
        return dict(servers) if isinstance(servers, dict) else {}

    async def _materialize_runtime_content(
        self,
        *,
        content: str,
        attachments: Any,
        cwd: str | None,
        session_id: str,
    ) -> Any:
        if not isinstance(attachments, list) or not attachments:
            return content
        blocks: list[dict[str, Any]] = [{"type": "text", "text": content}]
        downloadable = False
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            path_hint = _optional_string(attachment.get("pathHint") or attachment.get("path"))
            if path_hint:
                blocks.append({"type": "text", "text": f"\n\nAttached file: {path_hint}"})
                continue
            if _attachment_file_id(attachment) is not None:
                downloadable = True

        if not downloadable:
            return blocks
        if self.attachment_downloader is None:
            logger.warning("dropping {} Claude attachments - no downloader is wired", len(attachments))
            blocks.append(
                {
                    "type": "text",
                    "text": "\n\n[Attachments could not be loaded: connector downloader unavailable]",
                }
            )
            return blocks

        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            if _optional_string(attachment.get("pathHint") or attachment.get("path")):
                continue
            file_id = _attachment_file_id(attachment)
            if file_id is None:
                continue
            try:
                data, original_name, media_type = await self.attachment_downloader(
                    session_id, file_id
                )
            except Exception as exc:
                logger.exception("Claude attachment download failed file_id={}", file_id)
                blocks.append({"type": "text", "text": f"\n\n[Failed to load attachment {file_id}: {exc}]"})
                continue
            original_name = original_name or _attachment_name_from(attachment) or file_id
            media_type = media_type or _optional_string(attachment.get("mediaType")) or "application/octet-stream"
            target = attachment_target(session_id, file_id, original_name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            try:
                target.chmod(0o600)
            except OSError:
                pass
            if media_type.startswith("image/"):
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.b64encode(data).decode("ascii"),
                        },
                    }
                )
                blocks.append({"type": "text", "text": f"\n\nAttached image: {original_name} at {target}"})
            else:
                blocks.append(
                    {
                        "type": "text",
                        "text": (
                            f"\n\n[Attached file: {original_name} ({media_type},"
                            f" {len(data)} bytes) at {target}]"
                        ),
                    }
                )
        return blocks


async def _prompt_stream(content: Any):
    yield {
        "type": "user",
        "message": {
            "role": "user",
            "content": content,
        },
    }


def _attachments_metadata(params: dict[str, Any]) -> list[dict[str, Any]] | None:
    attachments = params.get("attachments")
    if not isinstance(attachments, list) or not attachments:
        return None
    metadata: list[dict[str, Any]] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        item: dict[str, Any] = {}
        for source_key, target_key in (
            ("fileId", "fileId"),
            ("id", "fileId"),
            ("name", "name"),
            ("mediaType", "mediaType"),
            ("size", "size"),
            ("sha256", "sha256"),
        ):
            value = attachment.get(source_key)
            if value is not None and target_key not in item:
                item[target_key] = value
        if item:
            metadata.append(item)
    return metadata or None


def _pending_client_messages(runtime: _SdkSessionRuntime) -> list[dict[str, Any]]:
    if not runtime.current_client_message_id:
        return []
    message: dict[str, Any] = {"clientMessageId": runtime.current_client_message_id}
    if runtime.current_content is not None:
        message["text"] = runtime.current_content
    if runtime.current_attachments:
        message["attachments"] = runtime.current_attachments
    return [message]


def _record_stderr(runtime: _SdkSessionRuntime, line: str) -> None:
    cleaned = _redact(line.strip())
    if not cleaned:
        return
    runtime.stderr_lines.append(cleaned)
    if len(runtime.stderr_lines) > _MAX_STDERR_LINES:
        del runtime.stderr_lines[: len(runtime.stderr_lines) - _MAX_STDERR_LINES]
    logger.warning("claude sdk stderr session_id={} line={}", runtime.session_id, cleaned)


def _filter_live_task_events(
    runtime: _SdkSessionRuntime,
    events: list[Any],
) -> list[Any]:
    out: list[Any] = []
    for event in events:
        tool_use_id = _optional_string(getattr(event, "toolUseId", None))
        if tool_use_id and getattr(event, "toolResult", None) is None and is_task_event_tool_name(getattr(event, "toolName", None)):
            runtime.ignored_task_tool_use_ids.add(tool_use_id)
            continue
        if tool_use_id and getattr(event, "toolResult", None) is not None and tool_use_id in runtime.ignored_task_tool_use_ids:
            continue
        out.append(event)
    return out


def _stderr_excerpt(lines: list[str]) -> str | None:
    if not lines:
        return None
    text = "\n".join(lines[-_MAX_STDERR_LINES:])
    if len(text) > _MAX_STDERR_CHARS:
        return "..." + text[-_MAX_STDERR_CHARS:]
    return text


def _failure_message(exc: Exception, stderr: str | None) -> str:
    message = str(exc)
    if stderr:
        return f"{message}\n\nClaude stderr:\n{stderr}"
    return message


def _redact(value: str) -> str:
    return _SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}***", value)


async def _maybe_await(method: Any) -> None:
    if not callable(method):
        return
    result = method()
    if hasattr(result, "__await__"):
        await result


async def _disconnect_client(client: Any) -> None:
    # Best-effort teardown of a superseded SDK client. Try disconnect() then
    # close(); a failure here must never fail the new turn, so swallow it.
    for method_name in ("disconnect", "close"):
        method = getattr(client, method_name, None)
        if callable(method):
            try:
                await _maybe_await(method)
            except Exception:
                logger.debug("claude sdk client {} failed", method_name, exc_info=True)
            return


def _sdk_message_to_raw(
    message: Any,
    fallback_session_id: str | None,
) -> dict[str, Any] | None:
    content = _extract_attr(message, "content")
    role = _message_role(message)
    if content is None and role is None:
        return None
    blocks = _blocks_to_dicts(content)
    session_id = (
        _optional_string(_extract_attr(message, "session_id", "sessionId"))
        or fallback_session_id
        or "unknown"
    )
    message_id = _optional_string(_extract_attr(message, "message_id", "messageId"))
    textless_blocks = _without_text_blocks(blocks)
    if _has_text_blocks(blocks) and message_id is None:
        if textless_blocks:
            blocks = textless_blocks
        else:
            logger.warning(
                "dropping Claude SDK text message without message_id role={} session_id={}",
                role,
                session_id,
            )
            return None
    if not blocks:
        logger.warning(
            "dropping Claude SDK message with no reducible blocks role={} session_id={}",
            role,
            session_id,
        )
        return None
    source_event_id = _optional_string(_extract_attr(message, "uuid")) or message_id or "unknown"
    return {
        "uuid": source_event_id,
        "session_id": session_id,
        "timestamp": _optional_string(_extract_attr(message, "timestamp")) or utc_now(),
        "parent_tool_use_id": _optional_string(
            _extract_attr(message, "parent_tool_use_id", "parentToolUseId")
        ),
        "message": {
            "id": message_id,
            "role": role,
            "content": blocks,
        },
    }


def _result_message_to_raw(message: Any, fallback_session_id: str | None) -> dict[str, Any] | None:
    text = _optional_string(_extract_attr(message, "result"))
    if not text:
        return None
    message_id = _optional_string(_extract_attr(message, "uuid"))
    if message_id is None:
        logger.warning(
            "dropping Claude result text without uuid session_id={}",
            _optional_string(_extract_attr(message, "session_id", "sessionId")) or fallback_session_id,
        )
        return None
    session_id = (
        _optional_string(_extract_attr(message, "session_id", "sessionId"))
        or fallback_session_id
        or "unknown"
    )
    return {
        "uuid": message_id,
        "session_id": session_id,
        "timestamp": utc_now(),
        "message": {
            "id": message_id,
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def _turn_usage_from_result(message: Any) -> dict[str, Any] | None:
    """Flatten a ResultMessage's usage + cost into the turn.end content.usage
    shape clients render. ResultMessage.usage mirrors the API usage block
    (input/output/cache tokens); total_cost_usd is the turn's dollar cost.
    Returns None when neither is present so turn.end stays lean on failure."""
    usage = _extract_attr(message, "usage")
    usage = usage if isinstance(usage, dict) else None
    cost = _extract_attr(message, "total_cost_usd", "totalCostUsd")
    if usage is None and cost is None:
        return None
    out: dict[str, Any] = {}
    if usage is not None:
        input_tokens = _int(usage.get("input_tokens")) or 0
        output_tokens = _int(usage.get("output_tokens")) or 0
        cache_creation = _int(usage.get("cache_creation_input_tokens")) or 0
        cache_read = _int(usage.get("cache_read_input_tokens")) or 0
        out["inputTokens"] = input_tokens
        out["outputTokens"] = output_tokens
        out["cacheCreationTokens"] = cache_creation
        out["cacheReadTokens"] = cache_read
        # The context-window occupancy of the last API call: everything the
        # model saw as input this turn (fresh input + both cache tiers) plus
        # what it produced. This is the number CLI /context sums.
        out["totalTokens"] = input_tokens + cache_creation + cache_read + output_tokens
    if isinstance(cost, (int, float)):
        out["costUsd"] = float(cost)
    return out or None


def _context_usage_from_response(raw: Any) -> dict[str, Any] | None:
    """Flatten a ContextUsageResponse (get_context_usage() / CLI /context) into
    the compact session-level gauge clients render: current tokens, the
    effective ceiling, percent used, and whether autocompact is armed. Returns
    None when the payload lacks the totals that make a gauge meaningful."""
    if not isinstance(raw, dict):
        return None
    total = _int(raw.get("totalTokens"))
    max_tokens = _int(raw.get("maxTokens"))
    if total is None and max_tokens is None:
        return None
    percentage = raw.get("percentage")
    out: dict[str, Any] = {}
    if total is not None:
        out["totalTokens"] = total
    if max_tokens is not None:
        out["maxTokens"] = max_tokens
    if isinstance(percentage, (int, float)):
        out["percentage"] = float(percentage)
    elif total is not None and max_tokens:
        out["percentage"] = round(total / max_tokens * 100, 1)
    model = _optional_string(raw.get("model"))
    if model:
        out["model"] = model
    auto_compact = raw.get("isAutoCompactEnabled")
    if isinstance(auto_compact, bool):
        out["autoCompactEnabled"] = auto_compact
    threshold = _int(raw.get("autoCompactThreshold"))
    if threshold is not None:
        out["autoCompactThreshold"] = threshold
    return out or None


def _stream_event_to_raw(runtime: _SdkSessionRuntime, turn_id: str, message: Any) -> dict[str, Any] | None:
    event = _extract_attr(message, "event")
    if not isinstance(event, dict):
        return None
    event_type = _optional_string(event.get("type"))
    if event_type == "message_start":
        payload = event.get("message")
        runtime.partial_text_blocks.clear()
        runtime.partial_block_types.clear()
        if isinstance(payload, dict):
            runtime.partial_message_id = _optional_string(payload.get("id"))
        else:
            runtime.partial_message_id = None
        runtime.partial_message_uuid = _optional_string(_extract_attr(message, "uuid"))
        return None
    if event_type == "content_block_start":
        index = _int(event.get("index"))
        block = event.get("content_block")
        if index is None or not isinstance(block, dict):
            return None
        block_type = _stream_block_kind(_optional_string(block.get("type")))
        if block_type is None:
            return None
        # Register this index's block type so deltas route to the right
        # accumulator (thinking vs text) instead of being merged into one blob.
        runtime.partial_block_types[index] = block_type
        # thinking blocks start with the prose under `thinking`, text under
        # `text`; both usually start empty and grow via deltas.
        seed = _optional_string(block.get("thinking")) if block_type == "thinking" else _optional_string(block.get("text"))
        runtime.partial_text_blocks[index] = seed or ""
        return _partial_message_raw(runtime, turn_id, message)
    if event_type == "content_block_delta":
        index = _int(event.get("index"))
        delta = event.get("delta")
        if index is None or not isinstance(delta, dict):
            return None
        text = _text_from_stream_delta(delta)
        if text:
            # A delta may arrive before its content_block_start in rare orderings;
            # default the type from the delta itself so routing still works.
            if index not in runtime.partial_block_types:
                runtime.partial_block_types[index] = (
                    "thinking" if _optional_string(delta.get("type")) == "thinking_delta" else "text"
                )
            runtime.partial_text_blocks[index] = f"{runtime.partial_text_blocks.get(index, '')}{text}"
            return _partial_message_raw(runtime, turn_id, message)
    if event_type == "message_delta":
        return _partial_message_raw(runtime, turn_id, message)
    return None


def _partial_message_raw(runtime: _SdkSessionRuntime, turn_id: str, message: Any) -> dict[str, Any] | None:
    # Rebuild the message content array from per-index accumulators, preserving
    # block order and type. Thinking and text blocks share the same index space,
    # so we emit them as separate blocks (thinking -> reasoning card, text ->
    # message) rather than concatenating everything into one text blob.
    blocks: list[dict[str, Any]] = []
    for index in sorted(runtime.partial_text_blocks):
        text = runtime.partial_text_blocks[index]
        if not text:
            continue
        if runtime.partial_block_types.get(index) == "thinking":
            blocks.append({"type": "thinking", "thinking": text})
        else:
            blocks.append({"type": "text", "text": text})
    if not blocks:
        return None
    message_id = runtime.partial_message_id
    if message_id is None:
        logger.warning("dropping Claude stream text without message_start id turn_id={}", turn_id)
        return None
    return {
        "uuid": runtime.partial_message_uuid or message_id,
        "session_id": _optional_string(_extract_attr(message, "session_id", "sessionId")) or runtime.external_session_id or "unknown",
        "timestamp": utc_now(),
        "parent_tool_use_id": _optional_string(_extract_attr(message, "parent_tool_use_id", "parentToolUseId")),
        "message": {
            "id": message_id,
            "role": "assistant",
            "content": blocks,
        },
    }


def _stream_block_kind(block_type: str | None) -> str | None:
    """Classify a content_block's type into the accumulator bucket it belongs to.

    Returns "thinking" for extended-thinking blocks, "text" for visible text,
    or None for blocks that don't stream prose (tool_use, redacted_thinking).
    """
    if block_type == "thinking":
        return "thinking"
    if block_type in {"text", None}:
        return "text"
    return None


def _text_from_stream_delta(delta: dict[str, Any]) -> str | None:
    delta_type = _optional_string(delta.get("type"))
    if delta_type in {"text", "text_delta"}:
        return _optional_string(delta.get("text"))
    if delta_type == "thinking_delta":
        return _optional_string(delta.get("thinking"))
    if delta_type in {"input_json_delta", "signature_delta"}:
        # Tool-input streaming and thinking signatures are not user-facing prose.
        return None
    return _optional_string(delta.get("text"))


def _is_streaming_assistant_message(item: dict[str, Any]) -> bool:
    return (
        item.get("type") == "message"
        and item.get("role") == "assistant"
        and isinstance(item.get("id"), str)
    )


def _is_tool_item(item: dict[str, Any]) -> bool:
    return item.get("type") == "tool" and isinstance(item.get("id"), str)


def _is_streaming_reasoning_item(item: dict[str, Any]) -> bool:
    # Reasoning (thinking) items stream in just like assistant text: their
    # deltas arrive incrementally and must go through the same live-stream
    # version management (revision bump, orderSeq preservation, convergence
    # with the final aggregated block) rather than being re-emitted as a new
    # card per delta. Identity is the block-indexed reasoning id, so the
    # streaming deltas and the final ThinkingBlock collapse onto one item.
    content = item.get("content")
    return (
        item.get("type") == "system"
        and isinstance(item.get("id"), str)
        and isinstance(content, dict)
        and content.get("kind") == "reasoning"
    )


def _prepare_live_stream_item(
    runtime: _SdkSessionRuntime,
    item: dict[str, Any],
) -> dict[str, Any] | None:
    item_id = _optional_string(item.get("id"))
    if item_id is None:
        return item
    existing = runtime.live_stream_items.get(item_id)
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    content_hash = _hash_content(content)
    now = utc_now()
    if existing is not None and existing.get("contentHash") == content_hash:
        return None
    if existing is None:
        prepared = dict(item)
        prepared["orderSeq"] = _next_order(runtime)
        prepared["revision"] = 1
        prepared["status"] = "running"
        prepared["contentHash"] = content_hash
        prepared["createdAt"] = item.get("createdAt") or now
        prepared["updatedAt"] = item.get("updatedAt") or now
        prepared.pop("completedAt", None)
    else:
        prepared = dict(item)
        prepared["orderSeq"] = existing.get("orderSeq")
        prepared["revision"] = int(existing.get("revision") or 1) + 1
        prepared["status"] = "running"
        prepared["contentHash"] = content_hash
        prepared["createdAt"] = existing.get("createdAt") or item.get("createdAt") or now
        prepared["updatedAt"] = item.get("updatedAt") or now
        prepared.pop("completedAt", None)
    runtime.live_stream_items[item_id] = prepared
    return prepared


def _prepare_live_stream_final_item(
    runtime: _SdkSessionRuntime,
    item: dict[str, Any],
) -> dict[str, Any] | None:
    item_id = _optional_string(item.get("id"))
    if item_id is None:
        return None
    existing = runtime.live_stream_items.get(item_id)
    if existing is None:
        return None
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    content_hash = _hash_content(content)
    finalized = dict(item)
    finalized["orderSeq"] = existing.get("orderSeq")
    finalized["revision"] = int(existing.get("revision") or 1) + (
        0 if existing.get("contentHash") == content_hash and existing.get("status") == "done" else 1
    )
    finalized["status"] = "done"
    finalized["contentHash"] = content_hash
    finalized["createdAt"] = existing.get("createdAt") or item.get("createdAt") or utc_now()
    finalized["updatedAt"] = item.get("updatedAt") or utc_now()
    finalized["completedAt"] = finalized["updatedAt"]
    runtime.live_stream_items[item_id] = finalized
    return finalized


def _prepare_live_tool_item(
    runtime: _SdkSessionRuntime,
    item: dict[str, Any],
) -> dict[str, Any] | None:
    item_id = _optional_string(item.get("id"))
    if item_id is None:
        return item
    existing = runtime.live_tool_items.get(item_id)
    incoming_content = item.get("content") if isinstance(item.get("content"), dict) else {}
    now = utc_now()
    if existing is None:
        prepared = dict(item)
        # Fold in any sub-agent progress that arrived before this parent Agent
        # card streamed in (stashed in _emit_task_progress, keyed by tool_use_id).
        stash_key = _optional_string(incoming_content.get("toolUseId"))
        stashed = runtime.subagent_progress.get(stash_key) if stash_key else None
        if stashed is not None:
            merged_content = dict(incoming_content)
            merged_content["subagent"] = stashed
            prepared["content"] = merged_content
        prepared["orderSeq"] = _next_order(runtime)
        prepared["revision"] = int(prepared.get("revision") or 1)
        prepared["contentHash"] = _hash_content(prepared.get("content") if isinstance(prepared.get("content"), dict) else {})
        prepared["createdAt"] = item.get("createdAt") or now
        prepared["updatedAt"] = item.get("updatedAt") or now
        if prepared.get("status") not in {"done", "failed", "interrupted", "cancelled"}:
            prepared.pop("completedAt", None)
        runtime.live_tool_items[item_id] = prepared
        return prepared

    merged_content = dict(existing.get("content") if isinstance(existing.get("content"), dict) else {})
    merged_content.update(incoming_content)
    content_hash = _hash_content(merged_content)
    incoming_status = _optional_string(item.get("status")) or _optional_string(existing.get("status")) or "running"
    if existing.get("contentHash") == content_hash and existing.get("status") == incoming_status:
        return None
    prepared = dict(existing)
    prepared["content"] = merged_content
    prepared["status"] = incoming_status
    prepared["role"] = item.get("role") or existing.get("role")
    prepared["revision"] = int(existing.get("revision") or 1) + 1
    prepared["contentHash"] = content_hash
    prepared["updatedAt"] = item.get("updatedAt") or now
    if incoming_status in {"done", "failed", "interrupted", "cancelled"}:
        prepared["completedAt"] = item.get("completedAt") or prepared["updatedAt"]
    else:
        prepared.pop("completedAt", None)
    runtime.live_tool_items[item_id] = prepared
    return prepared


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _blocks_to_dicts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if not isinstance(content, (list, tuple)):
        return []
    blocks: list[dict[str, Any]] = []
    for block in content:
        block_type = _optional_string(_extract_attr(block, "type"))
        if block_type is None:
            block_type = _block_type_from_class(block)
        if block_type == "text":
            text = _optional_string(_extract_attr(block, "text"))
            if text is None or not text.strip():
                continue
            blocks.append({"type": "text", "text": text})
        elif block_type == "thinking":
            # Extended-thinking block. The SDK's ThinkingBlock and the raw JSONL
            # both carry the prose under `thinking` (not `text`); `signature` is
            # often an empty string and is not needed downstream.
            text = _optional_string(_extract_attr(block, "thinking")) or _optional_string(
                _extract_attr(block, "text")
            )
            if text is None or not text.strip():
                continue
            blocks.append({"type": "thinking", "text": text})
        elif block_type == "redacted_thinking":
            # Encrypted thinking: the prose is not recoverable (only an opaque
            # `data` field). The live SDK parser drops these outright, but raw
            # history JSONL can still carry them, so surface a placeholder rather
            # than dropping silently or crashing on the missing `thinking` field.
            blocks.append({"type": "thinking", "text": "", "redacted": True})
        elif block_type == "tool_use":
            blocks.append(
                {
                    "type": "tool_use",
                    "id": _optional_string(_extract_attr(block, "id")) or _stable_message_id(block),
                    "name": _optional_string(_extract_attr(block, "name")) or "unknown",
                    "input": _extract_attr(block, "input") or {},
                }
            )
        elif block_type == "tool_result":
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": _optional_string(_extract_attr(block, "tool_use_id", "toolUseId")) or "",
                    "content": _extract_attr(block, "content"),
                    "is_error": _extract_attr(block, "is_error", "isError"),
                }
            )
    return blocks


def _has_text_blocks(blocks: list[dict[str, Any]]) -> bool:
    return any(block.get("type") == "text" and isinstance(block.get("text"), str) for block in blocks)


def _without_text_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [block for block in blocks if block.get("type") != "text"]


def _role_from_class(value: Any) -> str | None:
    name = value.__class__.__name__.lower()
    if "assistant" in name:
        return "assistant"
    if "user" in name:
        return "user"
    if "system" in name:
        return "system"
    return None


def _message_role(message: Any) -> str | None:
    return _optional_string(_extract_attr(message, "role")) or _role_from_class(message)


def _block_type_from_class(value: Any) -> str:
    name = value.__class__.__name__.lower()
    if "tooluse" in name or "tool_use" in name:
        return "tool_use"
    if "toolresult" in name or "tool_result" in name:
        return "tool_result"
    if "thinking" in name:
        return "thinking"
    return "text"


def _is_result_message(message: Any) -> bool:
    name = message.__class__.__name__.lower()
    return "result" in name


def _is_stream_event(message: Any) -> bool:
    return message.__class__.__name__.lower() == "streamevent"


# Sub-agent (Task/Agent) progress lifecycle. These are the four SystemMessage
# subclasses the SDK emits on the live stream while a sub-agent runs; matched by
# class name to stay consistent with _is_result_message / _is_stream_event and
# to survive the SDK exposing them as plain SystemMessage instances. Confirmed
# empirically that the live receive_response() stream carries task_started,
# task_updated and task_notification (task_progress only on longer runs); none
# are ever written to the transcript JSONL, so this is a real-time-only signal.
_TASK_MESSAGE_CLASSES = frozenset(
    {
        "taskstartedmessage",
        "taskprogressmessage",
        "taskupdatedmessage",
        "tasknotificationmessage",
    }
)

# Terminal sub-agent statuses. task_updated reports the raw "killed"; a
# task_notification maps that to "stopped". Either means the sub-agent finished.
_TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "stopped", "killed"})


def _is_rate_limit_message(message: Any) -> bool:
    # Matched by class name to stay consistent with _is_result_message /
    # _is_task_progress_message and survive the SDK handing us a plain
    # SystemMessage. RateLimitEvent is emitted on the live stream when the CLI's
    # throttling state changes (allowed -> allowed_warning -> rejected and back).
    if message.__class__.__name__.lower() == "ratelimitevent":
        return True
    subtype = _optional_string(_extract_attr(message, "subtype"))
    return subtype == "rate_limit_event"


def _rate_limit_from_message(message: Any) -> dict[str, Any] | None:
    """Flatten a RateLimitEvent into the session-level rateLimit shape clients
    render. Returns None when there is no usable status to surface."""
    # The typed RateLimitEvent exposes rate_limit_info (a RateLimitInfo); a bare
    # SystemMessage keeps the same payload under data["rate_limit_info"]. Accept
    # either, and read the info's fields as attributes or dict keys.
    info = _extract_attr(message, "rate_limit_info", "rateLimitInfo")
    if info is None:
        data = _extract_attr(message, "data")
        if isinstance(data, dict):
            info = data.get("rate_limit_info") or data.get("rateLimitInfo")
    if info is None:
        return None
    status = _optional_string(_extract_attr(info, "status"))
    if status is None and isinstance(info, dict):
        status = _optional_string(info.get("status"))
    if not status:
        return None
    out: dict[str, Any] = {"status": status}

    def _info_field(*names: str) -> Any:
        value = _extract_attr(info, *names)
        if value is None and isinstance(info, dict):
            for name in names:
                if name in info:
                    return info[name]
        return value

    limit_type = _optional_string(_info_field("rate_limit_type", "rateLimitType"))
    if limit_type:
        out["type"] = limit_type
    resets_at = _int(_info_field("resets_at", "resetsAt"))
    if resets_at is not None:
        out["resetsAt"] = resets_at
    utilization = _info_field("utilization")
    if isinstance(utilization, (int, float)) and not isinstance(utilization, bool):
        out["utilization"] = float(utilization)
    overage_status = _optional_string(_info_field("overage_status", "overageStatus"))
    if overage_status:
        out["overageStatus"] = overage_status
    overage_resets_at = _int(_info_field("overage_resets_at", "overageResetsAt"))
    if overage_resets_at is not None:
        out["overageResetsAt"] = overage_resets_at
    return out


def _is_hook_event_message(message: Any) -> bool:
    # HookEventMessage (SystemMessage subclass) arrives when include_hook_events
    # is enabled. Matched by class name to stay consistent with the other
    # predicates and survive the SDK handing us a plain SystemMessage; the
    # hook_* subtypes are the wire-level fallback.
    if message.__class__.__name__.lower() == "hookeventmessage":
        return True
    subtype = _optional_string(_extract_attr(message, "subtype"))
    return subtype in {"hook_started", "hook_response"}


def _notification_from_hook_message(message: Any) -> dict[str, Any] | None:
    """Extract a user-facing notification from a Notification hook event.

    Returns None for every other hook (which we enable en masse via
    include_hook_events but only surface Notification from) and for the
    hook_started phase (we act on the completed hook_response only, so a single
    Notification produces one timeline item, not two)."""
    event_name = _optional_string(_extract_attr(message, "hook_event_name", "hookEventName"))
    data = _extract_attr(message, "data")
    data = data if isinstance(data, dict) else {}
    if event_name is None:
        event_name = _optional_string(data.get("hook_event_name") or data.get("hookEventName"))
    if event_name != "Notification":
        return None
    subtype = _optional_string(_extract_attr(message, "subtype")) or _optional_string(data.get("subtype"))
    if subtype == "hook_started":
        return None
    # The Notification payload rides under data; the hook input is nested under
    # data["input"] on some CLI builds and flat on others. Accept both.
    payload = data.get("input") if isinstance(data.get("input"), dict) else data
    message_text = _optional_string(payload.get("message")) or _optional_string(data.get("message"))
    if not message_text:
        return None
    out: dict[str, Any] = {"message": message_text}
    title = _optional_string(payload.get("title")) or _optional_string(data.get("title"))
    if title:
        out["title"] = title
    notification_type = _optional_string(payload.get("notification_type") or payload.get("notificationType"))
    if notification_type:
        out["notificationType"] = notification_type
    return out


def _is_task_progress_message(message: Any) -> bool:
    if message.__class__.__name__.lower() in _TASK_MESSAGE_CLASSES:
        return True
    # Fallback: a plain SystemMessage whose subtype is one of the task_* kinds.
    subtype = _optional_string(_extract_attr(message, "subtype"))
    return subtype in {"task_started", "task_progress", "task_updated", "task_notification"}


def _task_progress_from_message(message: Any) -> dict[str, Any] | None:
    """Flatten a task_* system message into the content.subagent shape clients
    render. Returns None when the message lacks a task_id (nothing to anchor)."""
    task_id = _optional_string(_extract_attr(message, "task_id", "taskId"))
    subtype = _optional_string(_extract_attr(message, "subtype"))
    # A bare SystemMessage keeps its payload under `data`; the typed subclasses
    # expose the same fields as attributes. Read attributes first, fall back to
    # the data dict so both shapes work.
    data = _extract_attr(message, "data")
    data = data if isinstance(data, dict) else {}
    if task_id is None:
        task_id = _optional_string(data.get("task_id"))
    if task_id is None:
        return None
    tool_use_id = _optional_string(_extract_attr(message, "tool_use_id", "toolUseId")) or _optional_string(
        data.get("tool_use_id")
    )
    status = _optional_string(_extract_attr(message, "status")) or _optional_string(data.get("status"))
    # task_updated carries its status inside a patch dict when the attribute is
    # unset; prefer the explicit field but fall back to the patch.
    if status is None:
        patch = _extract_attr(message, "patch")
        patch = patch if isinstance(patch, dict) else data.get("patch")
        if isinstance(patch, dict):
            status = _optional_string(patch.get("status"))
    description = _optional_string(_extract_attr(message, "description")) or _optional_string(
        data.get("description")
    )
    summary = _optional_string(_extract_attr(message, "summary")) or _optional_string(data.get("summary"))
    last_tool = _optional_string(_extract_attr(message, "last_tool_name")) or _optional_string(
        data.get("last_tool_name")
    )
    usage = _extract_attr(message, "usage")
    usage = usage if isinstance(usage, dict) else data.get("usage")
    progress: dict[str, Any] = {"taskId": task_id, "subtype": subtype or "task_updated"}
    if tool_use_id:
        progress["toolUseId"] = tool_use_id
    if status:
        progress["status"] = status
    if description:
        progress["description"] = description
    if summary:
        progress["summary"] = summary
    if last_tool:
        progress["lastToolName"] = last_tool
    if isinstance(usage, dict):
        progress["usage"] = {
            "totalTokens": _int(usage.get("total_tokens")) or 0,
            "toolUses": _int(usage.get("tool_uses")) or 0,
            "durationMs": _int(usage.get("duration_ms")) or 0,
        }
    return progress


def _merge_subagent_progress(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Fold a new task_* event onto the accumulated sub-agent state. Later
    non-empty fields win; a terminal status is sticky (a late non-terminal
    update can't un-finish a sub-agent), and usage is kept once seen."""
    merged = dict(existing) if isinstance(existing, dict) else {}
    prior_status = merged.get("status")
    for key, value in incoming.items():
        if value in (None, ""):
            continue
        merged[key] = value
    if prior_status in _TERMINAL_TASK_STATUSES and incoming.get("status") not in _TERMINAL_TASK_STATUSES:
        merged["status"] = prior_status
    merged["finished"] = merged.get("status") in _TERMINAL_TASK_STATUSES
    return merged


def _permission_allow(sdk: Any, input_data: dict[str, Any]) -> Any:
    cls = _optional_attr(sdk, "PermissionResultAllow", "types.PermissionResultAllow")
    if cls is not None:
        return cls(updated_input=input_data)
    return {"behavior": "allow", "updatedInput": input_data}


def _permission_deny(sdk: Any, message: str) -> Any:
    cls = _optional_attr(sdk, "PermissionResultDeny", "types.PermissionResultDeny")
    if cls is not None:
        return cls(message=message)
    return {"behavior": "deny", "message": message}


def _optional_attr(root: Any, *paths: str) -> Any:
    for path in paths:
        current = root
        for part in path.split("."):
            current = getattr(current, part, None)
            if current is None:
                break
        if current is not None:
            return current
    return None


def _extract_attr(value: Any, *names: str) -> Any:
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _turn_start_item(runtime: _SdkSessionRuntime, turn_id: str) -> dict[str, Any]:
    return _timeline_item(
        id=f"{turn_id}:turn-start",
        session_id=runtime.session_id,
        turn_id=turn_id,
        item_type="turn.start",
        status="running",
        role=None,
        content={},
        external_session_id=runtime.external_session_id,
        source_item_type="turn.start",
        derived_key="turn-start",
        order_seq=_next_order(runtime),
    )


def _turn_end_item(
    runtime: _SdkSessionRuntime,
    turn_id: str,
    *,
    status: str,
    result: str,
    stop_reason: str,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content: dict[str, Any] = {"stopReason": stop_reason, "result": result}
    if usage:
        content["usage"] = usage
    return _timeline_item(
        id=f"{turn_id}:turn-end",
        session_id=runtime.session_id,
        turn_id=turn_id,
        item_type="turn.end",
        status=status,
        role=None,
        content=content,
        external_session_id=runtime.external_session_id,
        source_item_type="turn.end",
        derived_key="turn-end",
        order_seq=_next_order(runtime),
    )


def _timeline_item(
    *,
    id: str,
    session_id: str,
    turn_id: str,
    item_type: str,
    status: str,
    role: str | None,
    content: dict[str, Any],
    external_session_id: str | None,
    source_item_type: str,
    derived_key: str | None = None,
    source_extra: dict[str, Any] | None = None,
    order_seq: int,
) -> dict[str, Any]:
    now = utc_now()
    source: dict[str, Any] = {
        "runtime": "claude",
        "sessionId": external_session_id,
        "turnId": turn_id,
        "itemId": id,
        "itemType": source_item_type,
        "event": source_item_type,
    }
    if derived_key:
        source["derivedKey"] = derived_key
    if source_extra:
        source.update(source_extra)
    return {
        "id": id,
        "sessionId": session_id,
        "turnId": turn_id,
        "type": item_type,
        "status": status,
        "role": role,
        "content": content,
        "source": source,
        "orderSeq": order_seq,
        "revision": 1,
        "contentHash": _hash_content(content),
        "createdAt": now,
        "updatedAt": now,
        "completedAt": now if status in {"done", "failed", "interrupted", "cancelled"} else None,
    }


def _next_order(runtime: _SdkSessionRuntime) -> int:
    order_seq = runtime.next_order_seq
    runtime.next_order_seq += 1
    return order_seq


def _approval_payload(
    *,
    approval_id: str,
    runtime: _SdkSessionRuntime,
    tool_name: str,
    input_data: dict[str, Any],
) -> dict[str, Any]:
    kind = _approval_kind(tool_name)
    # AskUserQuestion is not a gate ("run it or not") but a prompt for the user to
    # pick from N options. Signal that with kind="question" + choices=["answer",
    # "reject"] so clients render a question card; the questions payload carries
    # the options.
    # Gate tools offer "approve for session" so the client can render the
    # remember-my-choice button; the connector then auto-allows identical calls
    # for the rest of the session (see _can_use_tool / session_approved_rules).
    # AskUserQuestion is a prompt, not a gate, so it has no session-grant option.
    choices = (
        ["answer", "reject"]
        if tool_name == "AskUserQuestion"
        else ["approve", "approve_for_session", "reject"]
    )
    return {
        "id": approval_id,
        "sessionId": runtime.session_id,
        "turnId": runtime.active_turn_id,
        "status": "pending",
        "kind": kind,
        "title": f"Claude requests {tool_name}",
        "description": _approval_description(tool_name, input_data),
        "payload": {"toolName": tool_name, "input": input_data},
        "choices": choices,
        "source": {
            "runtime": "claude",
            "requestId": approval_id,
            "sessionId": runtime.external_session_id,
            "turnId": runtime.active_turn_id,
            "method": "can_use_tool",
        },
    }


def _approval_kind(tool_name: str) -> str:
    if tool_name == "Bash":
        return "command"
    if tool_name in {"Edit", "Write", "NotebookEdit"}:
        return "file_change"
    if tool_name == "AskUserQuestion":
        return "question"
    return "tool_call"


def _selections_to_answers(selections: Any) -> dict[str, Any]:
    """Convert client-sent selections into the CLI's `answers` map.

    Client sends: [{"question": "<question text>", "labels": ["<label>", ...]}].
    The CLI expects {question_text: answer_string | [answer_string, ...]}; a
    single label collapses to a string, multiple labels stay a list (the CLI
    joins them with ", " itself).
    """
    answers: dict[str, Any] = {}
    if not isinstance(selections, list):
        return answers
    for entry in selections:
        if not isinstance(entry, dict):
            continue
        question = entry.get("question")
        labels = entry.get("labels")
        if not isinstance(question, str) or not question:
            continue
        if isinstance(labels, str):
            answers[question] = labels
        elif isinstance(labels, list):
            values = [label for label in labels if isinstance(label, str) and label]
            if not values:
                continue
            answers[question] = values[0] if len(values) == 1 else values
    return answers


def _approval_description(tool_name: str, input_data: dict[str, Any]) -> str:
    if tool_name == "Bash":
        return _optional_string(input_data.get("command")) or "Run command"
    if tool_name in {"Edit", "Write", "NotebookEdit"}:
        return _optional_string(input_data.get("file_path")) or "Modify file"
    return json.dumps(input_data, ensure_ascii=False, sort_keys=True)


def _approval_id(session_id: str, turn_id: str | None, tool_name: str, input_data: dict[str, Any]) -> str:
    return "appr_" + _short_hash([session_id, turn_id, tool_name, input_data])


def _approval_rule_key(tool_name: str, input_data: dict[str, Any]) -> str:
    # Grant key for "approve for this session". Intentionally excludes
    # session_id/turn_id (the runtime set is already session-scoped, and the
    # grant must span turns) and is parameter-exact on the canonicalized input,
    # so a grant is scoped to the precise tool call the user actually saw.
    return "rule_" + _short_hash([tool_name, input_data])


def _turn_id(session_id: str, content: str) -> str:
    return "turn_claude_" + _short_hash([session_id, content, secrets.token_urlsafe(8)])


def _stable_message_id(value: Any) -> str:
    return "msg_" + _short_hash(repr(value))


def _hash_content(content: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _short_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]


def _required(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} is required")
    return value


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _positive_int(value: Any) -> int | None:
    # bool is an int subclass; reject it so a stray True/False never becomes 1/0.
    # Only a strictly positive integer is a usable max_turns cap; anything else
    # (0, negative, float, str) falls back to the SDK default (no cap).
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _attachment_file_id(att: Any) -> str | None:
    if isinstance(att, dict):
        candidate = att.get("fileId")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _attachment_name_from(att: Any) -> str | None:
    if isinstance(att, dict):
        candidate = att.get("name")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


__all__ = ["ClaudeSdkAdapter", "ClaudeSdkAdapterError"]
