from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from typing import Any

import pytest

from connector.claude.history_adapter import ClaudeHistoryAdapter
from connector.claude.sdk_adapter import ClaudeSdkAdapter, _approval_rule_key
from connector.launch import launch_target


@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class FakeToolResultBlock:
    tool_use_id: str
    content: Any
    is_error: bool = False
    type: str = "tool_result"


# Real SDK sub-agent progress subclasses. The adapter keys off the class name
# (see _TASK_MESSAGE_CLASSES) so the names here must match the SDK's exactly.
@dataclass
class TaskStartedMessage:
    task_id: str
    description: str | None = None
    tool_use_id: str | None = None
    session_id: str | None = None
    subtype: str = "task_started"


@dataclass
class TaskUpdatedMessage:
    task_id: str
    patch: dict[str, Any] | None = None
    status: str | None = None
    session_id: str | None = None
    subtype: str = "task_updated"


@dataclass
class TaskNotificationMessage:
    task_id: str
    status: str | None = None
    summary: str | None = None
    output_file: str | None = None
    tool_use_id: str | None = None
    usage: dict[str, Any] | None = None
    session_id: str | None = None
    subtype: str = "task_notification"


@dataclass
class FakeAssistantMessage:
    message_id: str | None
    content: list[Any]
    role: str = "assistant"
    uuid: str | None = None


@dataclass
class FakeSystemMessage:
    subtype: str
    data: dict[str, Any]


@dataclass
class FakeResultMessage:
    session_id: str
    subtype: str = "success"
    result: str = "ok"


@dataclass
class StreamEvent:
    event: dict[str, Any]
    session_id: str
    uuid: str = "stream_event_uuid"


class FakeOptions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeAllow:
    def __init__(self, *, updated_input):
        self.updated_input = updated_input


class FakeDeny:
    def __init__(self, *, message):
        self.message = message


class FakeHookMatcher:
    def __init__(self, *, matcher, hooks):
        self.matcher = matcher
        self.hooks = hooks


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, *, options):
        self.options = options
        self.connected = False
        self.queries: list[Any] = []
        self.interrupted = False
        self.model_calls: list = []
        self.permission_mode_calls: list = []
        FakeClient.instances.append(self)

    async def connect(self):
        self.connected = True

    async def query(self, prompt):
        self.queries.append(prompt)

    async def receive_response(self):
        yield FakeAssistantMessage(
            message_id="msg_assistant_1",
            content=[
                FakeTextBlock(text="I'll run that."),
                FakeToolUseBlock(id="toolu_1", name="Bash", input={"command": "pytest -q"}),
            ],
        )
        yield FakeResultMessage(session_id="claude_session_1")

    async def interrupt(self):
        self.interrupted = True

    async def set_model(self, model):
        self.model_calls.append(model)

    async def set_permission_mode(self, mode):
        self.permission_mode_calls.append(mode)


class FailingClient(FakeClient):
    async def connect(self):
        stderr = self.options.kwargs.get("stderr")
        if stderr:
            stderr("Error: auth_token=secret-token")
            stderr("real failure detail")
        raise RuntimeError("Command failed with exit code 1")


class SystemThenAssistantClient(FakeClient):
    async def receive_response(self):
        yield FakeSystemMessage(subtype="init", data={})
        yield FakeAssistantMessage(
            message_id="msg_assistant_after_system",
            content=[FakeTextBlock(text="still streaming")],
        )
        yield FakeResultMessage(session_id="claude_session_system")


class SessionMetaClient(FakeClient):
    async def receive_response(self):
        # An init system message carrying real bootstrap metadata, yielded twice
        # to mimic a reconnect storm; sessionMeta must be emitted exactly once.
        init_data = {
            "model": "claude-sonnet-5",
            "mcp_servers": [
                {"name": "filesystem", "status": "connected"},
                "playwright",
            ],
            "slash_commands": ["compact", "review"],
        }
        yield FakeSystemMessage(subtype="init", data=dict(init_data))
        yield FakeSystemMessage(subtype="init", data=dict(init_data))
        yield FakeAssistantMessage(
            message_id="msg_meta",
            content=[FakeTextBlock(text="ready")],
        )
        yield FakeResultMessage(session_id="claude_session_meta")


class StreamingDeltaClient(FakeClient):
    async def receive_response(self):
        yield StreamEvent(
            event={"type": "message_start", "message": {"id": "msg_stream_1"}},
            session_id="claude_session_stream",
        )
        yield StreamEvent(
            event={
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hel"},
            },
            session_id="claude_session_stream",
        )
        yield StreamEvent(
            event={
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "lo"},
            },
            session_id="claude_session_stream",
        )
        yield FakeResultMessage(session_id="claude_session_stream")


class PartialAssistantMessagesClient(FakeClient):
    async def receive_response(self):
        yield FakeAssistantMessage(
            message_id="resp_partial_1",
            content=[FakeTextBlock(text="Starting")],
        )
        yield FakeAssistantMessage(
            message_id="resp_partial_2",
            content=[FakeTextBlock(text="Starting\n\nFull answer")],
        )
        yield FakeResultMessage(session_id="claude_session_partial_messages")


class MultiAssistantMessagesClient(FakeClient):
    async def receive_response(self):
        yield FakeAssistantMessage(
            message_id="resp_intro",
            content=[FakeTextBlock(text="First I will run a command.")],
        )
        yield FakeAssistantMessage(
            message_id="resp_after_tool",
            content=[FakeTextBlock(text="Command is done. Now the essay.")],
        )
        yield FakeAssistantMessage(
            message_id="resp_essay",
            content=[FakeTextBlock(text="You have unusual talent.")],
        )
        yield FakeResultMessage(session_id="claude_session_multi_messages")


class ToolResultClient(FakeClient):
    async def receive_response(self):
        yield FakeAssistantMessage(
            message_id="msg_assistant_tool",
            content=[
                FakeToolUseBlock(id="toolu_write", name="Write", input={"file_path": "/repo/app.py", "content": "print('hi')\n"}),
            ],
        )
        yield FakeAssistantMessage(
            message_id="msg_user_tool_result",
            role="user",
            content=[
                FakeToolResultBlock(tool_use_id="toolu_write", content="File created"),
            ],
        )
        yield FakeResultMessage(session_id="claude_session_tool_result")


class TaskUpdateClient(FakeClient):
    async def receive_response(self):
        yield FakeAssistantMessage(
            message_id="msg_task_update",
            content=[
                FakeToolUseBlock(
                    id="call_task_1",
                    name="TaskUpdate",
                    input={"taskId": "13", "status": "deleted", "description": "obsolete"},
                ),
            ],
        )
        yield FakeAssistantMessage(
            message_id="msg_task_result",
            role="user",
            content=[
                FakeToolResultBlock(
                    tool_use_id="call_task_1",
                    content="Updated task #13 deleted",
                ),
            ],
        )
        yield FakeAssistantMessage(
            message_id="msg_task_answer",
            content=[FakeTextBlock(text="Here is the answer.")],
        )
        yield FakeResultMessage(session_id="claude_session_task_update")


class SubagentProgressClient(FakeClient):
    """Agent tool card streams in first, then task_* progress lands on it."""

    async def receive_response(self):
        yield FakeAssistantMessage(
            message_id="msg_agent_spawn",
            content=[
                FakeToolUseBlock(
                    id="toolu_agent",
                    name="Agent",
                    input={"subagent_type": "general-purpose", "description": "audit deps"},
                ),
            ],
        )
        yield TaskStartedMessage(
            task_id="task_7",
            description="audit deps",
            tool_use_id="toolu_agent",
        )
        yield TaskUpdatedMessage(
            task_id="task_7",
            patch={"status": "running"},
        )
        yield TaskNotificationMessage(
            task_id="task_7",
            status="completed",
            tool_use_id="toolu_agent",
            usage={"total_tokens": 1234, "tool_uses": 5, "duration_ms": 4200},
        )
        yield FakeResultMessage(session_id="claude_session_subagent")


class SubagentProgressBeforeCardClient(FakeClient):
    """Progress arrives before the parent Agent tool card streams in (stash-fold)."""

    async def receive_response(self):
        yield TaskStartedMessage(
            task_id="task_9",
            description="run migration",
            tool_use_id="toolu_agent_late",
        )
        yield TaskNotificationMessage(
            task_id="task_9",
            status="completed",
            tool_use_id="toolu_agent_late",
            usage={"total_tokens": 42, "tool_uses": 1, "duration_ms": 100},
        )
        yield FakeAssistantMessage(
            message_id="msg_agent_late",
            content=[
                FakeToolUseBlock(
                    id="toolu_agent_late",
                    name="Agent",
                    input={"subagent_type": "general-purpose", "description": "run migration"},
                ),
            ],
        )
        yield FakeResultMessage(session_id="claude_session_subagent_late")


class BlockingClient(FakeClient):
    started: asyncio.Event
    release: asyncio.Event

    async def receive_response(self):
        self.started.set()
        await self.release.wait()
        yield FakeResultMessage(session_id="claude_session_live")


@dataclass
class UsageResultMessage:
    session_id: str
    usage: dict[str, Any] | None = None
    total_cost_usd: float | None = None
    subtype: str = "success"
    result: str = "done"
    uuid: str = "result_uuid_usage"


class ContextUsageClient(FakeClient):
    """A turn that ends with a ResultMessage carrying usage/cost and exposes the
    get_context_usage() RPC (mirrors the real SDK client)."""

    async def receive_response(self):
        yield FakeAssistantMessage(
            message_id="msg_usage_assistant",
            content=[FakeTextBlock(text="answer")],
        )
        yield UsageResultMessage(
            session_id="claude_session_usage",
            usage={
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": 200,
                "cache_read_input_tokens": 700,
            },
            total_cost_usd=0.0123,
        )

    async def get_context_usage(self):
        return {
            "totalTokens": 1050,
            "maxTokens": 200000,
            "percentage": 0.5,
            "model": "claude-opus-4-8",
            "isAutoCompactEnabled": True,
            "autoCompactThreshold": 180000,
        }


class ContextUsageUnavailableClient(FakeClient):
    """The RPC raises (older CLI / disconnect race); the turn must still finish
    cleanly and simply omit the gauge."""

    async def receive_response(self):
        yield FakeAssistantMessage(
            message_id="msg_usage_fail_assistant",
            content=[FakeTextBlock(text="answer")],
        )
        yield UsageResultMessage(session_id="claude_session_usage_fail")

    async def get_context_usage(self):
        raise RuntimeError("get_context_usage not supported")


@dataclass
class FakeRateLimitInfo:
    status: str
    resets_at: int | None = None
    rate_limit_type: str | None = None
    utilization: float | None = None
    overage_status: str | None = None
    overage_resets_at: int | None = None


@dataclass
class RateLimitEvent:
    # Class name matches the SDK's RateLimitEvent so _is_rate_limit_message picks
    # it up by name, exactly as the real live-stream message would be matched.
    session_id: str
    rate_limit_info: FakeRateLimitInfo
    uuid: str = "rate_limit_uuid"


class RateLimitWarningClient(FakeClient):
    """A turn that streams a rate-limit warning before the result. The connector
    must surface it on session.updated as rateLimit."""

    async def receive_response(self):
        yield FakeAssistantMessage(
            message_id="msg_rl_assistant",
            content=[FakeTextBlock(text="working")],
        )
        yield RateLimitEvent(
            session_id="claude_session_rl",
            rate_limit_info=FakeRateLimitInfo(
                status="allowed_warning",
                resets_at=1_800_000_000,
                rate_limit_type="five_hour",
                utilization=0.92,
            ),
        )
        yield FakeResultMessage(session_id="claude_session_rl")


class RateLimitClearedClient(FakeClient):
    """A rate-limit warning followed by an 'allowed' event: the warning must be
    cleared so the client stops showing it."""

    async def receive_response(self):
        yield RateLimitEvent(
            session_id="claude_session_rl_clear",
            rate_limit_info=FakeRateLimitInfo(
                status="rejected",
                resets_at=1_800_000_000,
                rate_limit_type="seven_day",
                utilization=1.0,
            ),
        )
        yield RateLimitEvent(
            session_id="claude_session_rl_clear",
            rate_limit_info=FakeRateLimitInfo(status="allowed"),
        )
        yield FakeAssistantMessage(
            message_id="msg_rl_clear_assistant",
            content=[FakeTextBlock(text="recovered")],
        )
        yield FakeResultMessage(session_id="claude_session_rl_clear")


class NotificationHookClient(FakeClient):
    """A Notification hook event (via include_hook_events) plus an unrelated
    PreToolUse hook event that must be swallowed. Only the Notification should
    reach the timeline, and only on the hook_response phase (not hook_started)."""

    async def receive_response(self):
        # hook_started for the Notification: must NOT produce an item (we act on
        # the completed response only).
        yield FakeSystemMessage(
            subtype="hook_started",
            data={"hook_event_name": "Notification", "input": {"message": "Needs your attention"}},
        )
        # An unrelated hook event that must be swallowed, never surfaced.
        yield FakeSystemMessage(
            subtype="hook_response",
            data={"hook_event_name": "PreToolUse", "input": {"tool_name": "Bash"}},
        )
        # The Notification hook_response: this is the one that surfaces.
        yield FakeSystemMessage(
            subtype="hook_response",
            data={
                "hook_event_name": "Notification",
                "input": {
                    "message": "Needs your attention",
                    "title": "Approval",
                    "notification_type": "permission",
                },
            },
        )
        yield FakeAssistantMessage(
            message_id="msg_hook_assistant",
            content=[FakeTextBlock(text="done")],
        )
        yield FakeResultMessage(session_id="claude_session_hook")


class FakeSdk:
    ClaudeAgentOptions = FakeOptions
    ClaudeSDKClient = FakeClient
    HookMatcher = FakeHookMatcher
    PermissionResultAllow = FakeAllow
    PermissionResultDeny = FakeDeny


class RecordingHistoryAdapter(ClaudeHistoryAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.consumed: list[tuple[str | None, str | None, str | None]] = []
        self.synced = 0
        self.sync_session_params: list[dict[str, Any]] = []

    async def mark_session_consumed(
        self,
        *,
        connector_id: str | None = None,
        external_session_id: str | None,
        cwd: str | None = None,
    ) -> None:
        self.consumed.append((connector_id, external_session_id, cwd))

    async def sync_session(self, params):
        self.sync_session_params.append(params)
        pending = params.get("pendingClientMessages") or []
        items = [
            {
                "id": "turn_history:turn-start",
                "sessionId": params["sessionId"],
                "turnId": "turn_history",
                "type": "turn.start",
                "status": "running",
                "role": None,
                "content": {},
                "source": {
                    "runtime": "claude",
                    "sessionId": params["externalSessionId"],
                    "turnId": "turn_history",
                    "itemId": "turn_history:turn-start",
                    "itemType": "turn.start",
                    "event": "turn.start",
                    "derivedKey": "turn-start",
                },
                "orderSeq": 1,
                "revision": 1,
                "contentHash": "sha256:history-start",
            },
            {
                "id": "claude_msg_history_user",
                "sessionId": params["sessionId"],
                "turnId": "turn_history",
                "type": "message",
                "status": "done",
                "role": "user",
                "content": {"text": "Run tests"},
                "source": {
                    "runtime": "claude",
                    "sessionId": params["externalSessionId"],
                    "turnId": "turn_history",
                    "itemId": "u1",
                    "itemType": "text",
                    "event": "u1:0",
                    "derivedKey": "message",
                    **({"clientMessageId": pending[0]["clientMessageId"]} if pending else {}),
                },
                "orderSeq": 2,
                "revision": 1,
                "contentHash": "sha256:history-user",
            },
        ]
        if pending and pending[0].get("attachments"):
            items[1]["content"]["attachments"] = pending[0]["attachments"]
        return {
            "backendNotifications": [
                {
                    "method": "timeline.sync",
                    "params": {
                        "sessionId": params["sessionId"],
                        "items": items,
                    },
                }
            ]
        }

    async def sync_existing_sessions(
        self,
        connector_id,
        *,
        limit=100,
        force=False,
        skip_external_session_ids=None,
        notification_sink=None,
    ):
        self.synced += 1
        self.skip_external_session_ids = skip_external_session_ids or set()
        if notification_sink is not None:
            await notification_sink([])
        return {"threads": ["sess_scanned"], "skippedThreads": [], "backendNotifications": []}


@pytest.mark.anyio
async def test_claude_sdk_adapter_streams_timeline_and_updates_external_session():
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    FakeClient.instances = []
    history_adapter = RecordingHistoryAdapter()
    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=FakeSdk, history_adapter=history_adapter)
    adapter.claude_target = launch_target("custom", "/opt/claude")

    created = await adapter.create_session({"sessionId": "sess_1", "cwd": "/repo"})
    started = await adapter.start_turn(
        {
            "sessionId": "sess_1",
            "cwd": "/repo",
            "content": "Run tests",
            "clientMessageId": "opt_1",
            "permissionMode": "acceptEdits",
            "model": "claude-sonnet-4-6",
            "effort": "high",
            "maxTurns": 25,
            "attachments": [
                {
                    "fileId": "file_1",
                    "name": "report.txt",
                    "mediaType": "text/plain",
                    "size": 12,
                    "sha256": "abc",
                    "downloadUrl": "/sessions/sess_1/attachments/file_1",
                    "pathHint": "/repo/.aa-attachments/file_1-report.txt",
                }
            ],
        }
    )
    await adapter._sessions["sess_1"].active_task

    assert created == {"sessionId": "sess_1", "externalSessionId": None, "backendNotifications": []}
    assert started["turnId"].startswith("turn_claude_")
    client = FakeClient.instances[-1]
    assert client.connected is True
    assert client.options.kwargs["cwd"] == "/repo"
    assert client.options.kwargs["cli_path"] == "/opt/claude"
    assert client.options.kwargs["permission_mode"] == "acceptEdits"
    assert client.options.kwargs["model"] == "claude-sonnet-4-6"
    assert client.options.kwargs["effort"] == "high"
    assert client.options.kwargs["include_partial_messages"] is True
    assert "can_use_tool" in client.options.kwargs
    assert "hooks" in client.options.kwargs
    assert client.options.kwargs["include_hook_events"] is True
    assert client.options.kwargs["max_turns"] == 25

    timeline = [params["item"] for method, params in notifications if method == "timeline.itemUpsert"]
    assert [item["type"] for item in timeline] == [
        "turn.start",
        "message",
        "message",
        "tool",
        "message",
        "tool",
        "turn.end",
    ]
    assert timeline[1]["role"] == "user"
    assert timeline[1]["source"]["clientMessageId"] == "opt_1"
    assert timeline[1]["content"]["attachments"] == [
        {
            "fileId": "file_1",
            "name": "report.txt",
            "mediaType": "text/plain",
            "size": 12,
            "sha256": "abc",
        }
    ]
    assert timeline[2]["id"].startswith("claude_msg_")
    assert not timeline[2]["id"].startswith(started["turnId"])
    assert timeline[2]["role"] == "assistant"
    assert timeline[2]["content"]["text"] == "I'll run that."
    assert timeline[2]["status"] == "running"
    assert timeline[2]["source"]["itemId"] == "msg_assistant_1"
    assert timeline[3]["content"]["toolName"] == "Bash"
    assert timeline[3]["content"]["kind"] == "command"
    assert timeline[3]["content"]["command"] == "pytest -q"
    assert timeline[3]["role"] == "tool"
    assert timeline[4]["id"] == timeline[2]["id"]
    assert timeline[4]["status"] == "done"
    assert timeline[4]["revision"] == timeline[2]["revision"] + 1
    # The Bash tool_use never received a tool_result (turn ended first), so the
    # turn-end sweep force-finalizes it instead of leaving it stranded at
    # "running". Same id as the running tool, status flipped to the turn status.
    assert timeline[5]["id"] == timeline[3]["id"]
    assert timeline[5]["type"] == "tool"
    assert timeline[5]["status"] == "done"
    assert timeline[5]["revision"] == timeline[3]["revision"] + 1
    assert timeline[-1]["status"] == "done"

    updates = [params for method, params in notifications if method == "session.updated"]
    assert any(update["externalSessionId"] == "claude_session_1" for update in updates)
    assert history_adapter.consumed == [(None, "claude_session_1", "/repo")]

    sync_notifications: list[list[dict[str, Any]]] = []

    async def sync_sink(notifications: list[dict[str, Any]]) -> None:
        sync_notifications.append(notifications)

    sync_result = await adapter.sync_existing_sessions("conn_x", notification_sink=sync_sink)
    assert sync_result["threads"] == ["sess_scanned"]
    assert sync_result["skippedThreads"] == []
    assert sync_notifications == [[]]

    prompt = client.queries[0]
    yielded = []
    async for item in prompt:
        yielded.append(item)
    assert yielded == [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Run tests"},
                    {
                        "type": "text",
                        "text": "\n\nAttached file: /repo/.aa-attachments/file_1-report.txt",
                    },
                ],
            },
        }
    ]


@pytest.mark.anyio
async def test_claude_sdk_adapter_merges_live_tool_result_into_tool_call():
    class ToolResultSdk(FakeSdk):
        ClaudeSDKClient = ToolResultClient

    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=ToolResultSdk)

    await adapter.start_turn(
        {
            "sessionId": "sess_1",
            "cwd": "/repo",
            "content": "write a file",
        }
    )
    await adapter._sessions["sess_1"].active_task

    tool_items = [
        params["item"]
        for method, params in notifications
        if method == "timeline.itemUpsert" and params["item"]["type"] == "tool"
    ]

    assert len(tool_items) == 2
    assert tool_items[0]["id"] == tool_items[1]["id"]
    assert tool_items[0]["status"] == "running"
    assert tool_items[1]["status"] == "done"
    assert tool_items[1]["content"]["kind"] == "file_change"
    assert tool_items[1]["content"]["changes"][0]["path"] == "/repo/app.py"
    assert tool_items[1]["content"]["changes"][0]["kind"] == {"type": "add"}
    assert tool_items[1]["content"]["result"] == "File created"
    assert tool_items[1]["content"]["outputPreview"] == "File created"


@pytest.mark.anyio
async def test_claude_sdk_adapter_filters_live_task_update_tool_events():
    class TaskUpdateSdk(FakeSdk):
        ClaudeSDKClient = TaskUpdateClient

    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=TaskUpdateSdk)
    await adapter.start_turn(
        {
            "sessionId": "sess_task_update",
            "cwd": "/repo",
            "externalSessionId": "claude_session_task_update",
            "content": "write",
            "clientMessageId": "opt_task_update",
        }
    )
    await adapter._sessions["sess_task_update"].active_task

    timeline = [params["item"] for method, params in notifications if method == "timeline.itemUpsert"]
    assert [item["type"] for item in timeline] == ["turn.start", "message", "message", "message", "turn.end"]
    assistant = [item for item in timeline if item["type"] == "message" and item["role"] == "assistant"]
    assert [item["content"]["text"] for item in assistant] == ["Here is the answer.", "Here is the answer."]
    assert not any(item["type"] == "tool" for item in timeline)


@pytest.mark.anyio
async def test_claude_sdk_adapter_merges_subagent_progress_into_parent_card():
    class SubagentSdk(FakeSdk):
        ClaudeSDKClient = SubagentProgressClient

    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=SubagentSdk)
    await adapter.start_turn(
        {
            "sessionId": "sess_subagent",
            "cwd": "/repo",
            "externalSessionId": "claude_session_subagent",
            "content": "spawn a sub-agent",
        }
    )
    await adapter._sessions["sess_subagent"].active_task

    tool_items = [
        params["item"]
        for method, params in notifications
        if method == "timeline.itemUpsert" and params["item"]["type"] == "tool"
    ]
    # The Agent card is the only tool card, re-upserted as each task_* event lands.
    assert len({item["id"] for item in tool_items}) == 1
    assert tool_items[0]["content"]["toolName"] == "Agent"
    final = tool_items[-1]
    subagent = final["content"]["subagent"]
    assert subagent["taskId"] == "task_7"
    # description carried from TaskStarted, sticky across the bare TaskUpdated.
    assert subagent["description"] == "audit deps"
    # terminal status + usage folded in from the TaskNotification.
    assert subagent["status"] == "completed"
    assert subagent["finished"] is True
    assert subagent["usage"] == {"totalTokens": 1234, "toolUses": 5, "durationMs": 4200}
    # revisions strictly increase as progress accumulates on the same card.
    revisions = [item["revision"] for item in tool_items]
    assert revisions == sorted(revisions)
    assert revisions[-1] > revisions[0]


@pytest.mark.anyio
async def test_claude_sdk_adapter_folds_stashed_subagent_progress_on_late_card():
    class SubagentLateSdk(FakeSdk):
        ClaudeSDKClient = SubagentProgressBeforeCardClient

    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=SubagentLateSdk)
    await adapter.start_turn(
        {
            "sessionId": "sess_subagent_late",
            "cwd": "/repo",
            "externalSessionId": "claude_session_subagent_late",
            "content": "spawn a sub-agent",
        }
    )
    await adapter._sessions["sess_subagent_late"].active_task

    tool_items = [
        params["item"]
        for method, params in notifications
        if method == "timeline.itemUpsert" and params["item"]["type"] == "tool"
    ]
    assert tool_items, "expected the parent Agent card to be emitted"
    # Progress that arrived before the card was stashed and folded on first prepare.
    final = tool_items[-1]
    subagent = final["content"]["subagent"]
    assert subagent["taskId"] == "task_9"
    assert subagent["description"] == "run migration"
    assert subagent["status"] == "completed"
    assert subagent["finished"] is True
    assert subagent["usage"] == {"totalTokens": 42, "toolUses": 1, "durationMs": 100}


@pytest.mark.anyio
async def test_claude_sdk_adapter_emits_turn_usage_and_context_gauge():
    class UsageSdk(FakeSdk):
        ClaudeSDKClient = ContextUsageClient

    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=UsageSdk)
    await adapter.start_turn(
        {
            "sessionId": "sess_usage",
            "cwd": "/repo",
            "externalSessionId": "claude_session_usage",
            "content": "hi",
        }
    )
    await adapter._sessions["sess_usage"].active_task

    # turn.end carries the per-turn usage flattened from ResultMessage.usage/cost.
    turn_end = next(
        params["item"]
        for method, params in notifications
        if method == "timeline.itemUpsert" and params["item"]["type"] == "turn.end"
    )
    usage = turn_end["content"]["usage"]
    assert usage["inputTokens"] == 100
    assert usage["outputTokens"] == 50
    assert usage["cacheCreationTokens"] == 200
    assert usage["cacheReadTokens"] == 700
    # totalTokens = input + cache_creation + cache_read + output.
    assert usage["totalTokens"] == 1050
    assert usage["costUsd"] == 0.0123

    # session.updated (emitted at idle) carries the context gauge captured from
    # get_context_usage() after the receive loop, while the client was connected.
    context_updates = [
        params["contextUsage"]
        for method, params in notifications
        if method == "session.updated" and params.get("contextUsage") is not None
    ]
    assert context_updates, "expected a session.updated carrying contextUsage"
    gauge = context_updates[-1]
    assert gauge["totalTokens"] == 1050
    assert gauge["maxTokens"] == 200000
    assert gauge["percentage"] == 0.5
    assert gauge["autoCompactEnabled"] is True


@pytest.mark.anyio
async def test_claude_sdk_adapter_turn_finishes_when_context_gauge_unavailable():
    class UsageFailSdk(FakeSdk):
        ClaudeSDKClient = ContextUsageUnavailableClient

    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=UsageFailSdk)
    await adapter.start_turn(
        {
            "sessionId": "sess_usage_fail",
            "cwd": "/repo",
            "externalSessionId": "claude_session_usage_fail",
            "content": "hi",
        }
    )
    await adapter._sessions["sess_usage_fail"].active_task

    # The RPC raised, so no gauge is attached, but the turn still ends cleanly.
    turn_end = next(
        params["item"]
        for method, params in notifications
        if method == "timeline.itemUpsert" and params["item"]["type"] == "turn.end"
    )
    assert turn_end["status"] == "done"
    assert not any(
        params.get("contextUsage") is not None
        for method, params in notifications
        if method == "session.updated"
    )


@pytest.mark.anyio
async def test_claude_sdk_adapter_emits_session_meta_once_from_init():
    class SessionMetaSdk(FakeSdk):
        ClaudeSDKClient = SessionMetaClient

    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(
        notification_sink=sink,
        sdk_module=SessionMetaSdk,
        history_adapter=RecordingHistoryAdapter(),
    )
    await adapter.start_turn(
        {
            "sessionId": "sess_meta",
            "cwd": "/repo",
            "externalSessionId": "claude_session_meta",
            "content": "hi",
        }
    )
    await adapter._sessions["sess_meta"].active_task

    # The init message is harvested into sessionMeta and rides session.updated.
    meta_updates = [
        params["sessionMeta"]
        for method, params in notifications
        if method == "session.updated" and params.get("sessionMeta") is not None
    ]
    # Replayed init (reconnect storm) must not re-emit: exactly one carrier.
    assert len(meta_updates) == 1, "sessionMeta must be emitted exactly once"
    meta = meta_updates[0]
    assert meta["model"] == "claude-sonnet-5"
    assert meta["mcpServers"] == ["filesystem", "playwright"]
    assert meta["slashCommands"] == ["compact", "review"]
    # permissionMode is intentionally not mirrored into sessionMeta.
    assert "permissionMode" not in meta

    # The init message must never surface as a timeline item (no content blocks).
    assert not any(
        method == "timeline.itemUpsert" and params["item"].get("role") == "system"
        for method, params in notifications
    )


@pytest.mark.anyio
async def test_claude_sdk_adapter_skips_active_session_during_history_scan():
    class BlockingSdk(FakeSdk):
        ClaudeSDKClient = BlockingClient

    BlockingClient.instances = []
    BlockingClient.started = asyncio.Event()
    BlockingClient.release = asyncio.Event()
    history_adapter = RecordingHistoryAdapter()
    adapter = ClaudeSdkAdapter(sdk_module=BlockingSdk, history_adapter=history_adapter)

    await adapter.start_turn(
        {
            "sessionId": "sess_live",
            "cwd": "/repo",
            "externalSessionId": "claude_session_live",
            "content": "hi",
        }
    )
    await BlockingClient.started.wait()

    sync_notifications: list[list[dict[str, Any]]] = []

    async def sync_sink(notifications: list[dict[str, Any]]) -> None:
        sync_notifications.append(notifications)

    sync_result = await adapter.sync_existing_sessions("conn_x", notification_sink=sync_sink)
    assert sync_result["threads"] == ["sess_scanned"]
    assert sync_result["skippedThreads"] == []
    assert history_adapter.skip_external_session_ids == {"claude_session_live"}
    assert sync_notifications == [[]]

    BlockingClient.release.set()
    await adapter._sessions["sess_live"].active_task


@pytest.mark.anyio
async def test_claude_sdk_adapter_does_not_treat_system_subtype_as_result():
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    class SystemSdk(FakeSdk):
        ClaudeSDKClient = SystemThenAssistantClient

    adapter = ClaudeSdkAdapter(
        notification_sink=sink,
        sdk_module=SystemSdk,
        history_adapter=RecordingHistoryAdapter(),
    )

    started = await adapter.start_turn(
        {
            "sessionId": "sess_system",
            "cwd": "/repo",
            "externalSessionId": "claude_session_system",
            "content": "hi",
            "clientMessageId": "opt_system",
        }
    )
    await adapter._sessions["sess_system"].active_task

    timeline = [params["item"] for method, params in notifications if method == "timeline.itemUpsert"]
    assert [item["type"] for item in timeline] == [
        "turn.start",
        "message",
        "message",
        "message",
        "turn.end",
    ]
    assert timeline[1]["role"] == "user"
    assert timeline[1]["source"]["clientMessageId"] == "opt_system"
    assert timeline[2]["role"] == "assistant"
    assert timeline[2]["id"] == timeline[3]["id"]
    assert timeline[2]["content"]["text"] == "still streaming"
    assert timeline[2]["status"] == "running"
    assert timeline[3]["status"] == "done"
    assert timeline[-1]["turnId"] == started["turnId"]

    assert not any(method == "timeline.sync" for method, _params in notifications)


@pytest.mark.anyio
async def test_claude_sdk_adapter_versions_live_stream_message_snapshots():
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    class StreamingSdk(FakeSdk):
        ClaudeSDKClient = StreamingDeltaClient

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=StreamingSdk)

    await adapter.start_turn(
        {
            "sessionId": "sess_stream",
            "cwd": "/repo",
            "externalSessionId": "claude_session_stream",
            "content": "say hello",
        }
    )
    await adapter._sessions["sess_stream"].active_task

    timeline = [params["item"] for method, params in notifications if method == "timeline.itemUpsert"]
    assistant = [
        item
        for item in timeline
        if item["type"] == "message" and item.get("role") == "assistant"
    ]

    assert assistant[0]["id"].startswith("claude_msg_")
    assert len({item["id"] for item in assistant}) == 1
    assert [item["content"]["text"] for item in assistant] == ["Hel", "Hello", "Hello"]
    assert [item["revision"] for item in assistant] == [1, 2, 3]
    assert [item["status"] for item in assistant] == ["running", "running", "done"]
    assert assistant[0]["orderSeq"] == assistant[1]["orderSeq"] == assistant[2]["orderSeq"]
    assert assistant[0]["createdAt"] == assistant[1]["createdAt"] == assistant[2]["createdAt"]
    assert assistant[-1]["completedAt"]


@pytest.mark.anyio
async def test_claude_sdk_adapter_keeps_distinct_sdk_assistant_messages_separate():
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    class MultiMessagesSdk(FakeSdk):
        ClaudeSDKClient = MultiAssistantMessagesClient

    adapter = ClaudeSdkAdapter(
        notification_sink=sink,
        sdk_module=MultiMessagesSdk,
        history_adapter=RecordingHistoryAdapter(),
    )

    started = await adapter.start_turn(
        {
            "sessionId": "sess_multi_messages",
            "cwd": "/repo",
            "externalSessionId": "claude_session_multi_messages",
            "content": "write",
        }
    )
    await adapter._sessions["sess_multi_messages"].active_task

    timeline = [params["item"] for method, params in notifications if method == "timeline.itemUpsert"]
    assistant = [
        item
        for item in timeline
        if item["type"] == "message" and item.get("role") == "assistant"
    ]

    assert len(assistant) == 6
    assert len({item["id"] for item in assistant}) == 3
    assert all(item["id"].startswith("claude_msg_") for item in assistant)
    assert all(item["turnId"] == started["turnId"] for item in assistant)
    assert {item["source"]["derivedKey"] for item in assistant} == {"message"}
    by_source_id: dict[str, list[dict[str, Any]]] = {}
    for item in assistant:
        by_source_id.setdefault(item["source"]["itemId"], []).append(item)
    assert set(by_source_id) == {"resp_intro", "resp_after_tool", "resp_essay"}
    expected_text = {
        "resp_intro": "First I will run a command.",
        "resp_after_tool": "Command is done. Now the essay.",
        "resp_essay": "You have unusual talent.",
    }
    for source_id, items in by_source_id.items():
        assert [item["content"]["text"] for item in items] == [expected_text[source_id], expected_text[source_id]]
        assert [item["revision"] for item in items] == [1, 2]
        assert [item["status"] for item in items] == ["running", "done"]


@pytest.mark.anyio
async def test_claude_sdk_adapter_approval_bridge_resolves_to_sdk_allow():
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=FakeSdk)
    runtime = adapter._runtime_for(
        "sess_approval",
        {"sessionId": "sess_approval", "externalSessionId": "claude_session_approval"},
    )
    runtime.active_turn_id = "turn_approval"

    task = asyncio.create_task(
        adapter._can_use_tool("Bash", {"command": "ls"}, {"session_id": "claude_session_approval"})
    )
    await asyncio.sleep(0)

    approvals = [params for method, params in notifications if method == "approval.requested"]
    assert len(approvals) == 1
    assert approvals[0]["kind"] == "command"
    # Gate tools offer "approve for session" so clients can render that button;
    # without it the approved_for_session persistence path is unreachable.
    assert "approve_for_session" in approvals[0]["choices"]
    result = await adapter.resolve_approval(
        {
            "sessionId": "sess_approval",
            "approvalId": approvals[0]["id"],
            "status": "approved",
        }
    )
    permission = await task

    assert result == {"resolved": True}
    assert isinstance(permission, FakeAllow)
    assert permission.updated_input == {"command": "ls"}


@pytest.mark.anyio
async def test_claude_sdk_adapter_identical_concurrent_approvals_get_distinct_ids():
    # Two identical tool calls (same tool_name + input) in one turn hash to the
    # same base approval id. Each must still register its own resolvable pending
    # entry; the second must not overwrite and orphan the first's future.
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=FakeSdk)
    runtime = adapter._runtime_for(
        "sess_dup",
        {"sessionId": "sess_dup", "externalSessionId": "claude_session_dup"},
    )
    runtime.active_turn_id = "turn_dup"
    ctx = {"session_id": "claude_session_dup"}

    first_task = asyncio.create_task(adapter._can_use_tool("Bash", {"command": "ls"}, ctx))
    await asyncio.sleep(0)
    second_task = asyncio.create_task(adapter._can_use_tool("Bash", {"command": "ls"}, ctx))
    await asyncio.sleep(0)

    approvals = [p for m, p in notifications if m == "approval.requested"]
    assert len(approvals) == 2
    ids = {p["id"] for p in approvals}
    assert len(ids) == 2  # distinct ids despite identical tool_name + input
    assert len(runtime.pending_approvals) == 2  # neither future was orphaned

    for approval in approvals:
        await adapter.resolve_approval(
            {"sessionId": "sess_dup", "approvalId": approval["id"], "status": "approved"}
        )

    first = await first_task
    second = await second_task
    assert isinstance(first, FakeAllow)
    assert isinstance(second, FakeAllow)


@pytest.mark.anyio
async def test_claude_sdk_adapter_approved_for_session_auto_allows_identical_calls():
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=FakeSdk)
    runtime = adapter._runtime_for(
        "sess_afs",
        {"sessionId": "sess_afs", "externalSessionId": "claude_session_afs"},
    )
    runtime.active_turn_id = "turn_afs"
    ctx = {"session_id": "claude_session_afs"}

    # First call to `Read /a.txt`: prompts, user approves for the session.
    task = asyncio.create_task(
        adapter._can_use_tool("Read", {"file_path": "/a.txt"}, ctx)
    )
    await asyncio.sleep(0)
    approvals = [p for m, p in notifications if m == "approval.requested"]
    assert len(approvals) == 1
    await adapter.resolve_approval(
        {
            "sessionId": "sess_afs",
            "approvalId": approvals[0]["id"],
            "status": "approved_for_session",
        }
    )
    first = await task
    assert isinstance(first, FakeAllow)

    # Second identical call: auto-allowed, no new approval.requested emitted.
    second = await adapter._can_use_tool("Read", {"file_path": "/a.txt"}, ctx)
    assert isinstance(second, FakeAllow)
    assert second.updated_input == {"file_path": "/a.txt"}
    approvals = [p for m, p in notifications if m == "approval.requested"]
    assert len(approvals) == 1  # still just the one from the first call

    # A different parameter is NOT covered by the grant: it prompts again.
    task = asyncio.create_task(
        adapter._can_use_tool("Read", {"file_path": "/b.txt"}, ctx)
    )
    await asyncio.sleep(0)
    approvals = [p for m, p in notifications if m == "approval.requested"]
    assert len(approvals) == 2
    await adapter.resolve_approval(
        {
            "sessionId": "sess_afs",
            "approvalId": approvals[-1]["id"],
            "status": "approved",
        }
    )
    await task


@pytest.mark.anyio
async def test_claude_sdk_adapter_session_grants_do_not_leak_across_sessions():
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    runtime_a = adapter._runtime_for(
        "sess_a",
        {"sessionId": "sess_a", "externalSessionId": "claude_session_a"},
    )
    runtime_a.active_turn_id = "turn_a"
    runtime_a.session_approved_rules.add(_approval_rule_key("Read", {"file_path": "/a.txt"}))

    # A brand-new session has its own empty grant set: the same call still prompts.
    runtime_b = adapter._runtime_for(
        "sess_b",
        {"sessionId": "sess_b", "externalSessionId": "claude_session_b"},
    )
    runtime_b.active_turn_id = "turn_b"
    assert not runtime_b.session_approved_rules

    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter.notification_sink = sink
    task = asyncio.create_task(
        adapter._can_use_tool("Read", {"file_path": "/a.txt"}, {"session_id": "claude_session_b"})
    )
    await asyncio.sleep(0)
    approvals = [p for m, p in notifications if m == "approval.requested"]
    assert len(approvals) == 1
    await adapter.resolve_approval(
        {"sessionId": "sess_b", "approvalId": approvals[0]["id"], "status": "approved"}
    )
    await task


@pytest.mark.anyio
async def test_claude_sdk_adapter_ask_user_question_emits_question_kind():
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=FakeSdk)
    runtime = adapter._runtime_for(
        "sess_q",
        {"sessionId": "sess_q", "externalSessionId": "claude_session_q"},
    )
    runtime.active_turn_id = "turn_q"

    question_input = {
        "questions": [
            {
                "header": "Push method",
                "question": "How should we push?",
                "multiSelect": False,
                "options": [
                    {"label": "HTTPS", "description": "use https"},
                    {"label": "SSH", "description": "use ssh"},
                ],
            }
        ]
    }
    task = asyncio.create_task(
        adapter._can_use_tool("AskUserQuestion", question_input, {"session_id": "claude_session_q"})
    )
    await asyncio.sleep(0)

    approvals = [params for method, params in notifications if method == "approval.requested"]
    assert len(approvals) == 1
    # AskUserQuestion is a question, not a gate: kind="question", choices offer
    # "answer" instead of "approve", and the questions payload rides along.
    assert approvals[0]["kind"] == "question"
    assert approvals[0]["choices"] == ["answer", "reject"]
    assert approvals[0]["payload"]["input"]["questions"][0]["header"] == "Push method"

    result = await adapter.resolve_approval(
        {
            "sessionId": "sess_q",
            "approvalId": approvals[0]["id"],
            "status": "approved",
            "selections": [{"question": "How should we push?", "labels": ["HTTPS"]}],
        }
    )
    permission = await task

    assert result == {"resolved": True}
    assert isinstance(permission, FakeAllow)
    # The user's selection is merged into the tool input under `answers`
    # (question text -> answer string) so the CLI surfaces it to the model.
    assert permission.updated_input["answers"] == {"How should we push?": "HTTPS"}
    assert permission.updated_input["questions"] == question_input["questions"]


@pytest.mark.anyio
async def test_claude_sdk_adapter_ask_user_question_multi_select_keeps_list():
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=FakeSdk)
    runtime = adapter._runtime_for(
        "sess_qm",
        {"sessionId": "sess_qm", "externalSessionId": "claude_session_qm"},
    )
    runtime.active_turn_id = "turn_qm"

    question_input = {
        "questions": [
            {
                "header": "Features",
                "question": "Which features?",
                "multiSelect": True,
                "options": [
                    {"label": "A", "description": ""},
                    {"label": "B", "description": ""},
                ],
            }
        ]
    }
    task = asyncio.create_task(
        adapter._can_use_tool("AskUserQuestion", question_input, {"session_id": "claude_session_qm"})
    )
    await asyncio.sleep(0)

    approvals = [params for method, params in notifications if method == "approval.requested"]
    result = await adapter.resolve_approval(
        {
            "sessionId": "sess_qm",
            "approvalId": approvals[0]["id"],
            "status": "approved",
            "selections": [{"question": "Which features?", "labels": ["A", "B"]}],
        }
    )
    permission = await task

    assert result == {"resolved": True}
    # Multiple labels stay a list; the CLI joins them with ", " itself.
    assert permission.updated_input["answers"] == {"Which features?": ["A", "B"]}


@pytest.mark.anyio
async def test_claude_sdk_adapter_ask_user_question_reject_without_answers():
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=FakeSdk)
    runtime = adapter._runtime_for(
        "sess_qr",
        {"sessionId": "sess_qr", "externalSessionId": "claude_session_qr"},
    )
    runtime.active_turn_id = "turn_qr"

    task = asyncio.create_task(
        adapter._can_use_tool(
            "AskUserQuestion",
            {"questions": [{"question": "Which?", "options": [{"label": "A"}]}]},
            {"session_id": "claude_session_qr"},
        )
    )
    await asyncio.sleep(0)

    approvals = [params for method, params in notifications if method == "approval.requested"]
    # Skip = reject with no selections: the tool is denied, no answers injected.
    result = await adapter.resolve_approval(
        {
            "sessionId": "sess_qr",
            "approvalId": approvals[0]["id"],
            "status": "rejected",
        }
    )
    permission = await task

    assert result == {"resolved": True}
    assert isinstance(permission, FakeDeny)


@pytest.mark.anyio
async def test_claude_sdk_adapter_materializes_file_attachment_to_user_dir(tmp_path, monkeypatch):
    FakeClient.instances = []
    workspace = tmp_path / "repo"
    workspace.mkdir()
    attachments_root = tmp_path / "runtime-attachments"
    monkeypatch.setenv("AGENT_CONNECTOR_ATTACHMENTS_ROOT", str(attachments_root))
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)

    async def download(session_id: str, file_id: str) -> tuple[bytes, str, str]:
        assert session_id == "sess_file"
        assert file_id == "file_1"
        return b"hello\n", "../notes.md", "text/markdown"

    adapter.attachment_downloader = download

    await adapter.create_session({"sessionId": "sess_file", "cwd": str(workspace)})
    await adapter.start_turn(
        {
            "sessionId": "sess_file",
            "cwd": str(workspace),
            "content": "Read this",
            "attachments": [{"fileId": "file_1", "name": "../notes.md"}],
        }
    )
    await adapter._sessions["sess_file"].active_task

    materialized = attachments_root / "sess_file" / "file_1-notes.md"
    assert materialized.read_bytes() == b"hello\n"
    prompt = FakeClient.instances[-1].queries[0]
    yielded = []
    async for item in prompt:
        yielded.append(item)
    assert yielded[0]["message"]["content"] == [
        {"type": "text", "text": "Read this"},
        {
            "type": "text",
            "text": (
                f"\n\n[Attached file: ../notes.md (text/markdown, 6 bytes) at"
                f" {materialized}]"
            ),
        },
    ]


@pytest.mark.anyio
async def test_claude_sdk_adapter_sends_image_attachment_as_base64_block(tmp_path, monkeypatch):
    FakeClient.instances = []
    workspace = tmp_path / "repo"
    workspace.mkdir()
    attachments_root = tmp_path / "runtime-attachments"
    monkeypatch.setenv("AGENT_CONNECTOR_ATTACHMENTS_ROOT", str(attachments_root))
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    image_bytes = b"\x89PNG\r\n\x1a\n"

    async def download(session_id: str, file_id: str) -> tuple[bytes, str, str]:
        assert session_id == "sess_image"
        assert file_id == "file_img"
        return image_bytes, "diagram.png", "image/png"

    adapter.attachment_downloader = download

    await adapter.create_session({"sessionId": "sess_image", "cwd": str(workspace)})
    await adapter.start_turn(
        {
            "sessionId": "sess_image",
            "cwd": str(workspace),
            "content": "Review diagram",
            "attachments": [{"fileId": "file_img", "name": "diagram.png"}],
        }
    )
    await adapter._sessions["sess_image"].active_task

    materialized = attachments_root / "sess_image" / "file_img-diagram.png"
    assert materialized.read_bytes() == image_bytes
    prompt = FakeClient.instances[-1].queries[0]
    yielded = []
    async for item in prompt:
        yielded.append(item)
    content = yielded[0]["message"]["content"]
    assert content[0] == {"type": "text", "text": "Review diagram"}
    assert content[1] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(image_bytes).decode("ascii"),
        },
    }
    assert content[2] == {"type": "text", "text": f"\n\nAttached image: diagram.png at {materialized}"}


@pytest.mark.anyio
async def test_claude_sdk_adapter_interrupt_calls_sdk_client():
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    runtime = adapter._runtime_for("sess_interrupt", {"sessionId": "sess_interrupt"})
    client = FakeClient(options=FakeOptions())
    runtime.client = client

    result = await adapter.interrupt_turn({"sessionId": "sess_interrupt"})

    assert result == {"interrupted": True}
    assert client.interrupted is True


@pytest.mark.anyio
async def test_claude_sdk_adapter_surfaces_stderr_on_turn_failure():
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    class FailingSdk(FakeSdk):
        ClaudeSDKClient = FailingClient

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=FailingSdk)
    await adapter.start_turn(
        {
            "sessionId": "sess_fail",
            "cwd": "/repo",
            "externalSessionId": "claude_session_fail",
            "content": "hi",
            "model": "claude-opus-4-8[1M]",
            "effort": "xhigh",
            "permissionMode": "bypassPermissions",
        }
    )
    await adapter._sessions["sess_fail"].active_task

    timeline = [params["item"] for method, params in notifications if method == "timeline.itemUpsert"]
    assert timeline[-1]["type"] == "turn.end"
    assert timeline[-1]["status"] == "failed"
    assert "real failure detail" in timeline[-1]["content"]["stopReason"]
    assert "secret-token" not in timeline[-1]["content"]["stopReason"]
    errors = [params for method, params in notifications if method == "runtime.error"]
    assert errors
    assert errors[-1]["stderr"] == "Error: auth_token=***\nreal failure detail"
    assert "real failure detail" in errors[-1]["message"]


@pytest.mark.anyio
async def test_claude_sdk_adapter_surfaces_rate_limit_warning_on_session_update():
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    class RateLimitSdk(FakeSdk):
        ClaudeSDKClient = RateLimitWarningClient

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=RateLimitSdk)
    await adapter.start_turn(
        {
            "sessionId": "sess_rl",
            "cwd": "/repo",
            "externalSessionId": "claude_session_rl",
            "content": "hi",
        }
    )
    await adapter._sessions["sess_rl"].active_task

    # The RateLimitEvent is no longer swallowed by the system branch: it rides a
    # session.updated as a flattened rateLimit snapshot.
    rate_updates = [
        params["rateLimit"]
        for method, params in notifications
        if method == "session.updated" and params.get("rateLimit") is not None
    ]
    assert rate_updates, "expected a session.updated carrying rateLimit"
    snapshot = rate_updates[-1]
    assert snapshot["status"] == "allowed_warning"
    assert snapshot["type"] == "five_hour"
    assert snapshot["resetsAt"] == 1_800_000_000
    assert snapshot["utilization"] == 0.92

    # The turn still finishes normally alongside the warning.
    turn_end = [
        params["item"]
        for method, params in notifications
        if method == "timeline.itemUpsert" and params["item"]["type"] == "turn.end"
    ]
    assert turn_end and turn_end[-1]["status"] == "done"


@pytest.mark.anyio
async def test_claude_sdk_adapter_clears_rate_limit_once_throttling_lifts():
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    class RateLimitClearSdk(FakeSdk):
        ClaudeSDKClient = RateLimitClearedClient

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=RateLimitClearSdk)
    await adapter.start_turn(
        {
            "sessionId": "sess_rl_clear",
            "cwd": "/repo",
            "externalSessionId": "claude_session_rl_clear",
            "content": "hi",
        }
    )
    await adapter._sessions["sess_rl_clear"].active_task

    # A "rejected" event set the snapshot; the following "allowed" supersedes it
    # with a status="allowed" snapshot (NOT None) — the DB write path only stores
    # the column when rateLimit is present, so a clear must be an explicit
    # allowed snapshot the client reads, not a dropped field.
    runtime = adapter._sessions["sess_rl_clear"]
    assert runtime.rate_limit == {"status": "allowed"}

    updates = [
        params
        for method, params in notifications
        if method == "session.updated" and params.get("rateLimit") is not None
    ]
    assert updates
    # The final rateLimit snapshot reads "allowed" so the client hides the warning.
    assert updates[-1]["rateLimit"]["status"] == "allowed"
    # But the "rejected" state WAS surfaced at least once before it cleared.
    saw_rejected = any(u["rateLimit"].get("status") == "rejected" for u in updates)
    assert saw_rejected


@pytest.mark.anyio
async def test_claude_sdk_adapter_surfaces_notification_hook_as_timeline_item():
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    class NotificationSdk(FakeSdk):
        ClaudeSDKClient = NotificationHookClient

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=NotificationSdk)
    await adapter.start_turn(
        {
            "sessionId": "sess_notif",
            "cwd": "/repo",
            "externalSessionId": "claude_session_notif",
            "content": "hi",
        }
    )
    await adapter._sessions["sess_notif"].active_task

    # Only the Notification hook_response surfaces a timeline item; the
    # hook_started phase and the non-Notification hook are swallowed.
    notif_items = [
        params["item"]
        for method, params in notifications
        if method == "timeline.itemUpsert"
        and params["item"]["type"] == "system"
        and params["item"]["content"].get("kind") == "notification"
    ]
    assert len(notif_items) == 1
    item = notif_items[0]
    assert item["content"]["message"] == "Needs your attention"
    assert item["content"]["title"] == "Approval"
    assert item["role"] == "system"

    # The turn still finishes normally.
    turn_end = [
        params["item"]
        for method, params in notifications
        if method == "timeline.itemUpsert" and params["item"]["type"] == "turn.end"
    ]
    assert turn_end and turn_end[-1]["status"] == "done"


# ---------------------------------------------------------------------------
# MCP injection + status RPC
# ---------------------------------------------------------------------------
#
# The design guarantees "no mcp.json = zero regression" (see design.md
# "Compatibility & Rollback"). These tests exercise `_options_kwargs` via the
# start_turn path — which is the only production caller — so any drift that
# leaks `mcp_servers` / `strict_mcp_config` into the SDK options dict on the
# default no-MCP path would show up here.


@pytest.mark.anyio
async def test_claude_sdk_adapter_does_not_inject_mcp_when_provider_returns_empty():
    """No mcp.json ⇒ options must be bit-identical to the pre-MCP shape.

    Regression guard for design.md's zero-regression acceptance criterion:
    an empty provider must not silently enable `strict_mcp_config`, which
    would flip SDK semantics for users who never opted into MCP.
    """
    FakeClient.instances = []
    calls: list[int] = []

    def empty_provider() -> dict[str, dict[str, Any]]:
        calls.append(1)
        return {}

    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk, mcp_config_provider=empty_provider)
    await adapter.start_turn(
        {"sessionId": "sess_mcp_empty", "cwd": "/repo", "content": "hi"}
    )
    await adapter._sessions["sess_mcp_empty"].active_task

    client = FakeClient.instances[-1]
    assert "mcp_servers" not in client.options.kwargs
    assert "strict_mcp_config" not in client.options.kwargs
    # Provider was called per-turn (design.md: "called on every turn so hand-edits
    # to mcp.json take effect without a connector restart").
    assert calls, "provider must be invoked on every turn"


@pytest.mark.anyio
async def test_claude_sdk_adapter_injects_mcp_servers_and_strict_when_configured():
    """Populated provider ⇒ SDK sees mcp_servers + strict_mcp_config=True.

    The dict is passed through verbatim (design.md: "field names align with
    SDK McpStdioServerConfig / McpHttpServerConfig / McpSSEServerConfig") so
    any renaming or filtering by the adapter would break MCP silently.
    """
    FakeClient.instances = []
    servers = {
        "docs": {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-example"],
            "env": {"API_KEY": "x"},
        },
        "browser": {
            "type": "http",
            "url": "https://mcp.example.com/mcp",
            "headers": {"Authorization": "Bearer x"},
        },
    }

    def provider() -> dict[str, dict[str, Any]]:
        return servers

    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk, mcp_config_provider=provider)
    await adapter.start_turn(
        {"sessionId": "sess_mcp_full", "cwd": "/repo", "content": "hi"}
    )
    await adapter._sessions["sess_mcp_full"].active_task

    client = FakeClient.instances[-1]
    # Copy — not the same object — but with identical content. The adapter
    # `dict(mcp_servers)` guards against provider mutation between turns.
    assert client.options.kwargs["mcp_servers"] == servers
    assert client.options.kwargs["mcp_servers"] is not servers
    # strict_mcp_config=True is only set when we opt into MCP; otherwise the
    # SDK's default discovery path stays enabled (design.md).
    assert client.options.kwargs["strict_mcp_config"] is True


@pytest.mark.anyio
async def test_claude_sdk_adapter_swallows_provider_failure_as_no_mcp():
    """A raising provider ⇒ log + continue with no MCP.

    A broken mcp.json must never be able to knock the runtime out —
    see design.md "Loader …退回'无 MCP'而不是让 turn 起不来".
    """
    FakeClient.instances = []

    def bad_provider() -> dict[str, dict[str, Any]]:
        raise RuntimeError("mcp.json is broken")

    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk, mcp_config_provider=bad_provider)
    await adapter.start_turn(
        {"sessionId": "sess_mcp_bad", "cwd": "/repo", "content": "hi"}
    )
    await adapter._sessions["sess_mcp_bad"].active_task

    client = FakeClient.instances[-1]
    assert "mcp_servers" not in client.options.kwargs
    assert "strict_mcp_config" not in client.options.kwargs


@pytest.mark.anyio
async def test_claude_sdk_adapter_mcp_status_returns_empty_when_session_unknown():
    """`mcp.status` on a never-created session ⇒ empty list, no exception.

    Clients call `mcp.status` opportunistically (they might race a session
    creation or the SDK might not yet expose the RPC). An error here would
    break the UI's status panel for a benign case.
    """
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    result = await adapter.get_mcp_status({"sessionId": "nope"})
    assert result == {"mcpServers": []}


@pytest.mark.anyio
async def test_claude_sdk_adapter_mcp_status_returns_empty_when_sdk_client_missing_method():
    """Older SDKs without `get_mcp_status` ⇒ empty list, not an error."""
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    runtime = adapter._runtime_for(
        "sess_mcp_status_old", {"sessionId": "sess_mcp_status_old"}
    )

    class LegacyClient:
        # No `get_mcp_status` method at all.
        pass

    runtime.client = LegacyClient()
    result = await adapter.get_mcp_status({"sessionId": "sess_mcp_status_old"})
    assert result == {"mcpServers": []}


@pytest.mark.anyio
async def test_claude_sdk_adapter_mcp_status_forwards_sdk_response_verbatim():
    """SDK response is passed through unmodified.

    Per design.md ("return the SDK response verbatim, don't remap"), we
    strip only non-dict outer payloads. The `mcpServers` array — including
    every field the SDK surfaces — is handed to callers as-is so future
    schema extensions don't require adapter changes.
    """
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    runtime = adapter._runtime_for(
        "sess_mcp_status_ok", {"sessionId": "sess_mcp_status_ok"}
    )
    sdk_response = {
        "mcpServers": [
            {
                "name": "docs",
                "status": "connected",
                "connectionStatus": {"kind": "connected"},
                "tools": [{"name": "docs.get", "annotations": {}}],
            }
        ]
    }

    class LiveClient:
        async def get_mcp_status(self) -> dict[str, Any]:
            return sdk_response

    runtime.client = LiveClient()
    result = await adapter.get_mcp_status({"sessionId": "sess_mcp_status_ok"})
    assert result == {"mcpServers": sdk_response["mcpServers"]}


@pytest.mark.anyio
async def test_claude_sdk_adapter_mcp_status_swallows_sdk_exception():
    """A failing `client.get_mcp_status()` ⇒ empty list, no traceback bubble.

    Same rationale as the "provider raises" case: MCP status is best-effort
    telemetry, never a load-bearing dependency.
    """
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    runtime = adapter._runtime_for(
        "sess_mcp_status_fail", {"sessionId": "sess_mcp_status_fail"}
    )

    class ExplodingClient:
        async def get_mcp_status(self) -> dict[str, Any]:
            raise RuntimeError("mcp bridge crashed")

    runtime.client = ExplodingClient()
    result = await adapter.get_mcp_status({"sessionId": "sess_mcp_status_fail"})
    assert result == {"mcpServers": []}


@pytest.mark.anyio
async def test_claude_sdk_adapter_server_info_returns_error_when_session_unknown():
    """`get_server_info` on an unknown session → {ok: false}, no exception."""
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    result = await adapter.get_server_info({"sessionId": "nope"})
    assert result["ok"] is False


@pytest.mark.anyio
async def test_claude_sdk_adapter_server_info_returns_error_when_sdk_missing_method():
    """Older SDKs without `get_server_info` → {ok: false}, not an error."""
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    runtime = adapter._runtime_for(
        "sess_sinfo_old", {"sessionId": "sess_sinfo_old"}
    )

    class LegacyClient:
        pass

    runtime.client = LegacyClient()
    result = await adapter.get_server_info({"sessionId": "sess_sinfo_old"})
    assert result["ok"] is False
    assert "not available" in result.get("reason", "")


@pytest.mark.anyio
async def test_claude_sdk_adapter_server_info_forwards_sdk_response():
    """SDK response dict is returned with ok:True merged in."""
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    runtime = adapter._runtime_for(
        "sess_sinfo_ok", {"sessionId": "sess_sinfo_ok"}
    )
    sdk_payload = {
        "commands": [
            {"name": "/clear", "description": "Clear conversation history"},
            {"name": "/model", "description": "Switch model"},
        ],
        "output_style": "default",
    }

    class LiveClient:
        async def get_server_info(self) -> dict[str, Any]:
            return sdk_payload

    runtime.client = LiveClient()
    result = await adapter.get_server_info({"sessionId": "sess_sinfo_ok"})
    assert result["ok"] is True
    assert result["commands"] == sdk_payload["commands"]
    assert result["output_style"] == "default"


@pytest.mark.anyio
async def test_claude_sdk_adapter_server_info_swallows_sdk_exception():
    """A failing `client.get_server_info()` → {ok: false}, no traceback bubble."""
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    runtime = adapter._runtime_for(
        "sess_sinfo_fail", {"sessionId": "sess_sinfo_fail"}
    )

    class ExplodingClient:
        async def get_server_info(self) -> dict[str, Any]:
            raise RuntimeError("info unavailable")

    runtime.client = ExplodingClient()
    result = await adapter.get_server_info({"sessionId": "sess_sinfo_fail"})
    assert result["ok"] is False
    """rename_session calls sdk.rename_session with the right args and returns ok:True."""
    rename_calls: list[tuple[Any, ...]] = []

    class SdkWithRename:
        ClaudeAgentOptions = FakeSdk.ClaudeAgentOptions
        ClaudeSDKClient = FakeSdk.ClaudeSDKClient
        HookMatcher = FakeSdk.HookMatcher
        PermissionResultAllow = FakeSdk.PermissionResultAllow
        PermissionResultDeny = FakeSdk.PermissionResultDeny

        @staticmethod
        def rename_session(external_session_id: str, title: str, **kwargs: Any) -> None:
            rename_calls.append((external_session_id, title, kwargs))

    adapter = ClaudeSdkAdapter(sdk_module=SdkWithRename)
    result = await adapter.rename_session(
        {"externalSessionId": "ext123", "title": "New Title", "cwd": "/repo"}
    )

    assert result == {"ok": True}
    assert len(rename_calls) == 1
    assert rename_calls[0] == ("ext123", "New Title", {"directory": "/repo"})


@pytest.mark.anyio
async def test_claude_sdk_adapter_rename_session_without_cwd():
    """rename_session without cwd calls sdk.rename_session with only id and title."""
    rename_calls: list[tuple[Any, ...]] = []

    class SdkWithRename:
        ClaudeAgentOptions = FakeSdk.ClaudeAgentOptions
        ClaudeSDKClient = FakeSdk.ClaudeSDKClient
        HookMatcher = FakeSdk.HookMatcher
        PermissionResultAllow = FakeSdk.PermissionResultAllow
        PermissionResultDeny = FakeSdk.PermissionResultDeny

        @staticmethod
        def rename_session(external_session_id: str, title: str, **kwargs: Any) -> None:
            rename_calls.append((external_session_id, title, kwargs))

    adapter = ClaudeSdkAdapter(sdk_module=SdkWithRename)
    result = await adapter.rename_session(
        {"externalSessionId": "ext456", "title": "Another Title"}
    )

    assert result == {"ok": True}
    assert len(rename_calls) == 1
    # No directory kwarg when cwd is absent
    assert rename_calls[0] == ("ext456", "Another Title", {})


@pytest.mark.anyio
async def test_claude_sdk_adapter_rename_session_missing_sdk_method():
    """When sdk has no rename_session, return ok:False with a descriptive reason."""
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)  # FakeSdk has no rename_session
    result = await adapter.rename_session(
        {"externalSessionId": "ext789", "title": "Some Title"}
    )

    assert result["ok"] is False
    assert "rename_session" in result.get("reason", "")


@pytest.mark.anyio
async def test_claude_sdk_adapter_rename_session_missing_params():
    """Missing externalSessionId or title ⇒ ok:False immediately."""
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)

    # Missing title
    result_no_title = await adapter.rename_session({"externalSessionId": "ext1"})
    assert result_no_title["ok"] is False

    # Missing externalSessionId
    result_no_id = await adapter.rename_session({"title": "Some Title"})
    assert result_no_id["ok"] is False

    # Empty params
    result_empty = await adapter.rename_session({})
    assert result_empty["ok"] is False


@pytest.mark.anyio
async def test_claude_sdk_adapter_rename_session_sdk_raises():
    """When sdk.rename_session raises, return ok:False without propagating the exception."""

    class SdkWithRaisingRename:
        ClaudeAgentOptions = FakeSdk.ClaudeAgentOptions
        ClaudeSDKClient = FakeSdk.ClaudeSDKClient
        HookMatcher = FakeSdk.HookMatcher
        PermissionResultAllow = FakeSdk.PermissionResultAllow
        PermissionResultDeny = FakeSdk.PermissionResultDeny

        @staticmethod
        def rename_session(external_session_id: str, title: str, **kwargs: Any) -> None:
            raise RuntimeError("disk write failed")

    adapter = ClaudeSdkAdapter(sdk_module=SdkWithRaisingRename)
    result = await adapter.rename_session(
        {"externalSessionId": "ext_err", "title": "Bad Title"}
    )

    assert result["ok"] is False
    assert result.get("reason")


@pytest.mark.anyio
async def test_1m_model_suffix_strips_suffix_and_injects_betas():
    """[1M] suffix is stripped and betas injected; plain model passes through unchanged."""

    async def sink(method: str, params: dict[str, Any]) -> None:
        pass

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=FakeSdk, history_adapter=RecordingHistoryAdapter())

    # [1M] variant — suffix stripped, betas injected
    FakeClient.instances = []
    await adapter.start_turn(
        {"sessionId": "s1", "externalSessionId": "ext1", "content": "hi", "model": "claude-opus-4-8[1M]"}
    )
    # yield to let _drive_turn background task run until FakeClient is constructed
    for _ in range(10):
        await asyncio.sleep(0)
    assert FakeClient.instances, "FakeClient was not instantiated"
    opts = FakeClient.instances[-1].options
    assert opts.kwargs.get("model") == "claude-opus-4-8"
    assert "context-1m-2025-08-07" in (opts.kwargs.get("betas") or [])

    # plain model — no betas
    FakeClient.instances = []
    await adapter.start_turn(
        {"sessionId": "s2", "externalSessionId": "ext2", "content": "hi", "model": "claude-opus-4-8"}
    )
    for _ in range(10):
        await asyncio.sleep(0)
    assert FakeClient.instances
    opts_plain = FakeClient.instances[-1].options
    assert opts_plain.kwargs.get("model") == "claude-opus-4-8"
    assert not opts_plain.kwargs.get("betas")


@pytest.mark.anyio
async def test_stop_task_rpc_calls_client_stop_task():
    """stop_task delegates to client.stop_task and returns ok:True."""
    stopped: list[str] = []

    class StopCapturingClient(FakeClient):
        async def stop_task(self, task_id: str) -> None:  # type: ignore[override]
            stopped.append(task_id)

    class StopSdk(FakeSdk):
        ClaudeSDKClient = StopCapturingClient

    async def sink(method: str, params: dict[str, Any]) -> None:
        pass

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=StopSdk, history_adapter=RecordingHistoryAdapter())
    await adapter.start_turn({"sessionId": "s1", "externalSessionId": "ext1", "content": "hi"})
    # wait for _drive_turn background task to connect the client
    for _ in range(20):
        await asyncio.sleep(0)

    result = await adapter.stop_task({"sessionId": "s1", "taskId": "task-abc"})
    assert result == {"ok": True}
    assert stopped == ["task-abc"]


@pytest.mark.anyio
async def test_stop_task_no_active_client_returns_degraded():
    """stop_task returns ok:False when there is no active SDK client."""
    async def sink(method: str, params: dict[str, Any]) -> None:
        pass

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=FakeSdk)
    result = await adapter.stop_task({"sessionId": "s_unknown", "taskId": "task-xyz"})
    assert result["ok"] is False
    assert result.get("reason")


@pytest.mark.anyio
async def test_mcp_reconnect_rpc_calls_client_method():
    """reconnect_mcp_server delegates to client.reconnect_mcp_server and returns ok:True."""
    reconnected: list[str] = []

    class McpReconnectClient(FakeClient):
        async def reconnect_mcp_server(self, server_name: str) -> None:  # type: ignore[override]
            reconnected.append(server_name)

    class McpReconnectSdk(FakeSdk):
        ClaudeSDKClient = McpReconnectClient

    async def sink(method: str, params: dict[str, Any]) -> None:
        pass

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=McpReconnectSdk, history_adapter=RecordingHistoryAdapter())
    await adapter.start_turn({"sessionId": "s1", "externalSessionId": "ext1", "content": "hi"})
    for _ in range(20):
        await asyncio.sleep(0)

    result = await adapter.reconnect_mcp_server({"sessionId": "s1", "serverName": "my-server"})
    assert result == {"ok": True}
    assert reconnected == ["my-server"]


@pytest.mark.anyio
async def test_mcp_toggle_server_rpc_calls_client_method():
    """toggle_mcp_server delegates to client.toggle_mcp_server and returns ok:True."""
    toggled: list[tuple[str, bool]] = []

    class McpToggleClient(FakeClient):
        async def toggle_mcp_server(self, server_name: str, enabled: bool) -> None:  # type: ignore[override]
            toggled.append((server_name, enabled))

    class McpToggleSdk(FakeSdk):
        ClaudeSDKClient = McpToggleClient

    async def sink(method: str, params: dict[str, Any]) -> None:
        pass

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=McpToggleSdk, history_adapter=RecordingHistoryAdapter())
    await adapter.start_turn({"sessionId": "s1", "externalSessionId": "ext1", "content": "hi"})
    for _ in range(20):
        await asyncio.sleep(0)

    result = await adapter.toggle_mcp_server({"sessionId": "s1", "serverName": "my-server", "enabled": False})
    assert result == {"ok": True}
    assert toggled == [("my-server", False)]


@pytest.mark.anyio
async def test_context_usage_rpc_returns_usage():
    """get_context_usage delegates to client.get_context_usage and returns ok:True with usage."""
    fake_usage = {"totalTokens": 5000, "maxTokens": 200000, "percentage": 2.5}

    class ContextUsageClient(FakeClient):
        async def get_context_usage(self) -> dict[str, Any]:  # type: ignore[override]
            return fake_usage

    class ContextUsageSdk(FakeSdk):
        ClaudeSDKClient = ContextUsageClient

    async def sink(method: str, params: dict[str, Any]) -> None:
        pass

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=ContextUsageSdk, history_adapter=RecordingHistoryAdapter())
    await adapter.start_turn({"sessionId": "s1", "externalSessionId": "ext1", "content": "hi"})
    for _ in range(20):
        await asyncio.sleep(0)

    result = await adapter.get_context_usage({"sessionId": "s1"})
    assert result["ok"] is True
    assert "usage" in result
    usage = result["usage"]
    assert isinstance(usage, dict)
    assert usage.get("totalTokens") == 5000
    assert usage.get("maxTokens") == 200000


@pytest.mark.anyio
async def test_delete_session_rpc():
    """delete_session calls sdk.delete_session with the right args and returns ok:True."""
    delete_calls: list[tuple[Any, ...]] = []

    class SdkWithDelete:
        ClaudeAgentOptions = FakeSdk.ClaudeAgentOptions
        ClaudeSDKClient = FakeSdk.ClaudeSDKClient
        HookMatcher = FakeSdk.HookMatcher
        PermissionResultAllow = FakeSdk.PermissionResultAllow
        PermissionResultDeny = FakeSdk.PermissionResultDeny

        @staticmethod
        def delete_session(external_session_id: str, **kwargs: Any) -> None:
            delete_calls.append((external_session_id, kwargs))

    adapter = ClaudeSdkAdapter(sdk_module=SdkWithDelete)
    result = await adapter.delete_session(
        {"externalSessionId": "ext_del_1", "cwd": "/repo"}
    )

    assert result == {"ok": True}
    assert len(delete_calls) == 1
    assert delete_calls[0] == ("ext_del_1", {"directory": "/repo"})


@pytest.mark.anyio
async def test_delete_session_rpc_without_cwd():
    """delete_session without cwd calls sdk.delete_session with only the id."""
    delete_calls: list[tuple[Any, ...]] = []

    class SdkWithDelete:
        ClaudeAgentOptions = FakeSdk.ClaudeAgentOptions
        ClaudeSDKClient = FakeSdk.ClaudeSDKClient
        HookMatcher = FakeSdk.HookMatcher
        PermissionResultAllow = FakeSdk.PermissionResultAllow
        PermissionResultDeny = FakeSdk.PermissionResultDeny

        @staticmethod
        def delete_session(external_session_id: str, **kwargs: Any) -> None:
            delete_calls.append((external_session_id, kwargs))

    adapter = ClaudeSdkAdapter(sdk_module=SdkWithDelete)
    result = await adapter.delete_session({"externalSessionId": "ext_del_2"})

    assert result == {"ok": True}
    assert len(delete_calls) == 1
    assert delete_calls[0] == ("ext_del_2", {})


@pytest.mark.anyio
async def test_delete_session_rpc_missing_external_id():
    """delete_session without externalSessionId returns ok:False immediately."""
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    result = await adapter.delete_session({})
    assert result["ok"] is False
    assert "externalSessionId" in result.get("reason", "")


@pytest.mark.anyio
async def test_delete_session_rpc_missing_sdk_method():
    """When sdk has no delete_session, return ok:False with a descriptive reason."""
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)  # FakeSdk has no delete_session
    result = await adapter.delete_session({"externalSessionId": "ext_no_del"})
    assert result["ok"] is False
    assert "delete_session" in result.get("reason", "")


@pytest.mark.anyio
async def test_fork_session_rpc():
    """fork_session calls sdk.fork_session with the right args and returns ok:True with sessionId."""

    @dataclass
    class ForkResult:
        session_id: str

    fork_calls: list[tuple[Any, ...]] = []

    class SdkWithFork:
        ClaudeAgentOptions = FakeSdk.ClaudeAgentOptions
        ClaudeSDKClient = FakeSdk.ClaudeSDKClient
        HookMatcher = FakeSdk.HookMatcher
        PermissionResultAllow = FakeSdk.PermissionResultAllow
        PermissionResultDeny = FakeSdk.PermissionResultDeny

        @staticmethod
        def fork_session(external_session_id: str, **kwargs: Any) -> ForkResult:
            fork_calls.append((external_session_id, kwargs))
            return ForkResult(session_id="new-uuid-fork-1")

    adapter = ClaudeSdkAdapter(sdk_module=SdkWithFork)
    result = await adapter.fork_session(
        {
            "externalSessionId": "ext_fork_1",
            "cwd": "/repo",
            "upToMessageId": "msg_abc",
            "title": "My Fork",
        }
    )

    assert result == {"ok": True, "sessionId": "new-uuid-fork-1"}
    assert len(fork_calls) == 1
    assert fork_calls[0] == (
        "ext_fork_1",
        {"directory": "/repo", "up_to_message_id": "msg_abc", "title": "My Fork"},
    )


@pytest.mark.anyio
async def test_fork_session_rpc_minimal_params():
    """fork_session with only externalSessionId calls sdk.fork_session with no kwargs."""

    @dataclass
    class ForkResult:
        session_id: str

    fork_calls: list[tuple[Any, ...]] = []

    class SdkWithFork:
        ClaudeAgentOptions = FakeSdk.ClaudeAgentOptions
        ClaudeSDKClient = FakeSdk.ClaudeSDKClient
        HookMatcher = FakeSdk.HookMatcher
        PermissionResultAllow = FakeSdk.PermissionResultAllow
        PermissionResultDeny = FakeSdk.PermissionResultDeny

        @staticmethod
        def fork_session(external_session_id: str, **kwargs: Any) -> ForkResult:
            fork_calls.append((external_session_id, kwargs))
            return ForkResult(session_id="new-uuid-fork-2")

    adapter = ClaudeSdkAdapter(sdk_module=SdkWithFork)
    result = await adapter.fork_session({"externalSessionId": "ext_fork_2"})

    assert result == {"ok": True, "sessionId": "new-uuid-fork-2"}
    assert fork_calls[0] == ("ext_fork_2", {})


@pytest.mark.anyio
async def test_fork_session_rpc_missing_external_id():
    """fork_session without externalSessionId returns ok:False immediately."""
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    result = await adapter.fork_session({})
    assert result["ok"] is False
    assert "externalSessionId" in result.get("reason", "")


@pytest.mark.anyio
async def test_fork_session_rpc_missing_sdk_method():
    """When sdk has no fork_session, return ok:False with a descriptive reason."""
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)  # FakeSdk has no fork_session
    result = await adapter.fork_session({"externalSessionId": "ext_no_fork"})
    assert result["ok"] is False
    assert "fork_session" in result.get("reason", "")


@pytest.mark.anyio
async def test_exit_plan_mode_approval_sets_pending_permission_mode():
    """Approving ExitPlanMode sets pending_permission_mode from input_data."""
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=FakeSdk)
    runtime = adapter._runtime_for(
        "sess_plan",
        {"sessionId": "sess_plan", "externalSessionId": "claude_plan"},
    )
    runtime.active_turn_id = "turn_plan"

    task = asyncio.create_task(
        adapter._can_use_tool(
            "ExitPlanMode",
            {"permissionMode": "acceptEdits"},
            {"session_id": "claude_plan"},
        )
    )
    await asyncio.sleep(0)

    approvals = [params for method, params in notifications if method == "approval.requested"]
    assert len(approvals) == 1
    await adapter.resolve_approval(
        {"sessionId": "sess_plan", "approvalId": approvals[0]["id"], "status": "approved"}
    )
    await task

    assert runtime.pending_permission_mode == "acceptEdits"


# ---------------------------------------------------------------------------
# max_budget_usd passthrough
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_max_budget_usd_passed_to_options():
    """maxBudgetUsd in start_turn params is forwarded to ClaudeAgentOptions."""
    FakeClient.instances = []
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    await adapter.start_turn(
        {"sessionId": "sess_budget", "cwd": "/repo", "content": "hi", "maxBudgetUsd": 1.5}
    )
    await adapter._sessions["sess_budget"].active_task

    client = FakeClient.instances[-1]
    assert client.options.kwargs["max_budget_usd"] == 1.5


@pytest.mark.anyio
async def test_max_budget_usd_not_set_when_omitted():
    """When maxBudgetUsd is not provided, max_budget_usd is absent from options."""
    FakeClient.instances = []
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    await adapter.start_turn(
        {"sessionId": "sess_no_budget", "cwd": "/repo", "content": "hi"}
    )
    await adapter._sessions["sess_no_budget"].active_task

    client = FakeClient.instances[-1]
    assert "max_budget_usd" not in client.options.kwargs


@pytest.mark.anyio
async def test_max_budget_usd_accepts_string_float():
    """maxBudgetUsd as a string is coerced to float (JSON transport compatibility)."""
    FakeClient.instances = []
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    await adapter.start_turn(
        {"sessionId": "sess_budget_str", "cwd": "/repo", "content": "hi", "maxBudgetUsd": "2.0"}
    )
    await adapter._sessions["sess_budget_str"].active_task

    client = FakeClient.instances[-1]
    assert client.options.kwargs["max_budget_usd"] == 2.0


@pytest.mark.anyio
async def test_max_budget_usd_invalid_value_ignored():
    """A non-numeric maxBudgetUsd is silently ignored (no crash, key absent)."""
    FakeClient.instances = []
    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    await adapter.start_turn(
        {"sessionId": "sess_budget_bad", "cwd": "/repo", "content": "hi", "maxBudgetUsd": "not-a-number"}
    )
    await adapter._sessions["sess_budget_bad"].active_task

    client = FakeClient.instances[-1]
    assert "max_budget_usd" not in client.options.kwargs



@pytest.mark.anyio
async def test_tag_session_rpc():
    """tag_session calls sdk.tag_session with the right args and returns ok:True."""

    tag_calls: list[tuple[Any, ...]] = []

    class SdkWithTag:
        ClaudeAgentOptions = FakeSdk.ClaudeAgentOptions
        ClaudeSDKClient = FakeSdk.ClaudeSDKClient
        HookMatcher = FakeSdk.HookMatcher
        PermissionResultAllow = FakeSdk.PermissionResultAllow
        PermissionResultDeny = FakeSdk.PermissionResultDeny

        @staticmethod
        def tag_session(external_session_id: str, tag: str | None, *, directory: str | None = None) -> None:
            tag_calls.append((external_session_id, tag, directory))

    adapter = ClaudeSdkAdapter(sdk_module=SdkWithTag)
    result = await adapter.tag_session(
        {
            "externalSessionId": "ext_tag_1",
            "tag": "my-tag",
            "cwd": "/repo",
        }
    )

    assert result == {"ok": True}
    assert len(tag_calls) == 1
    assert tag_calls[0] == ("ext_tag_1", "my-tag", "/repo")


@pytest.mark.anyio
async def test_tag_session_rpc_clear_tag():
    """tag_session with tag=None clears the tag (passes None to sdk)."""

    tag_calls: list[tuple[Any, ...]] = []

    class SdkWithTag:
        ClaudeAgentOptions = FakeSdk.ClaudeAgentOptions
        ClaudeSDKClient = FakeSdk.ClaudeSDKClient
        HookMatcher = FakeSdk.HookMatcher
        PermissionResultAllow = FakeSdk.PermissionResultAllow
        PermissionResultDeny = FakeSdk.PermissionResultDeny

        @staticmethod
        def tag_session(external_session_id: str, tag: str | None, *, directory: str | None = None) -> None:
            tag_calls.append((external_session_id, tag, directory))

    adapter = ClaudeSdkAdapter(sdk_module=SdkWithTag)
    result = await adapter.tag_session(
        {
            "externalSessionId": "ext_tag_clear",
            "tag": None,
        }
    )

    assert result == {"ok": True}
    assert len(tag_calls) == 1
    assert tag_calls[0] == ("ext_tag_clear", None, None)


@pytest.mark.anyio
async def test_tag_session_rpc_without_cwd():
    """tag_session without cwd passes directory=None."""

    tag_calls: list[tuple[Any, ...]] = []

    class SdkWithTag:
        ClaudeAgentOptions = FakeSdk.ClaudeAgentOptions
        ClaudeSDKClient = FakeSdk.ClaudeSDKClient
        HookMatcher = FakeSdk.HookMatcher
        PermissionResultAllow = FakeSdk.PermissionResultAllow
        PermissionResultDeny = FakeSdk.PermissionResultDeny

        @staticmethod
        def tag_session(external_session_id: str, tag: str | None, *, directory: str | None = None) -> None:
            tag_calls.append((external_session_id, tag, directory))

    adapter = ClaudeSdkAdapter(sdk_module=SdkWithTag)
    result = await adapter.tag_session(
        {
            "externalSessionId": "ext_tag_no_cwd",
            "tag": "no-dir-tag",
        }
    )

    assert result == {"ok": True}
    assert tag_calls[0] == ("ext_tag_no_cwd", "no-dir-tag", None)


@pytest.mark.anyio
async def test_tag_session_rpc_missing_external_id():
    """tag_session without externalSessionId returns ok:False."""

    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)
    result = await adapter.tag_session({"tag": "orphan-tag"})
    assert result["ok"] is False
    assert "externalSessionId" in result.get("reason", "")


@pytest.mark.anyio
async def test_tag_session_rpc_missing_sdk_method():
    """When sdk has no tag_session, return ok:False with a descriptive reason."""

    adapter = ClaudeSdkAdapter(sdk_module=FakeSdk)  # FakeSdk has no tag_session
    result = await adapter.tag_session({"externalSessionId": "ext_no_tag", "tag": "x"})
    assert result["ok"] is False
    assert "tag_session" in result.get("reason", "")


    """ExitPlanMode without permissionMode in input falls back to 'acceptEdits'."""
    notifications: list[tuple[str, dict[str, Any]]] = []

    async def sink(method: str, params: dict[str, Any]) -> None:
        notifications.append((method, params))

    adapter = ClaudeSdkAdapter(notification_sink=sink, sdk_module=FakeSdk)
    runtime = adapter._runtime_for(
        "sess_plan_fb",
        {"sessionId": "sess_plan_fb", "externalSessionId": "claude_plan_fb"},
    )
    runtime.active_turn_id = "turn_plan_fb"

    task = asyncio.create_task(
        adapter._can_use_tool(
            "ExitPlanMode",
            {},  # no permissionMode field
            {"session_id": "claude_plan_fb"},
        )
    )
    await asyncio.sleep(0)

    approvals = [params for method, params in notifications if method == "approval.requested"]
    assert len(approvals) == 1
    await adapter.resolve_approval(
        {"sessionId": "sess_plan_fb", "approvalId": approvals[0]["id"], "status": "approved"}
    )
    await task

    assert runtime.pending_permission_mode == "acceptEdits"

