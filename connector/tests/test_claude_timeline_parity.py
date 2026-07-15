from __future__ import annotations

from connector.claude.normalizers import ClaudeLiveNormalizer, ClaudeTranscriptNormalizer
from connector.claude.timeline_identity import ClaudeTimelineIdentity
from connector.claude.timeline_reducer import ClaudeTimelineReducer


def test_live_and_transcript_normalizers_reduce_to_same_timeline_items():
    raw_turn = [
        {
            "uuid": "evt_user",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:00Z",
            "message": {
                "id": "msg_user_1",
                "role": "user",
                "content": [{"type": "text", "text": "Run the tests"}],
            },
        },
        {
            "uuid": "evt_assistant",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:01Z",
            "message": {
                "id": "msg_assistant_1",
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll run them."},
                    {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "pytest -q"}},
                ],
            },
        },
        {
            "uuid": "evt_assistant_duplicate_tool_use",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:01Z",
            "message": {
                "id": "msg_assistant_1",
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "pytest -q"}},
                ],
            },
        },
        {
            "uuid": "evt_tool_result",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:04Z",
            "message": {
                "id": "msg_user_tool_result",
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "249 passed"}],
            },
        },
    ]

    reducer = ClaudeTimelineReducer()
    live_items = reducer.reduce(
        session_id="sess_1",
        turn_id="turn_1",
        events=ClaudeLiveNormalizer().normalize(raw_turn),
    )
    transcript_items = reducer.reduce(
        session_id="sess_1",
        turn_id="turn_1",
        events=ClaudeTranscriptNormalizer().normalize(raw_turn),
    )

    assert [item["id"] for item in live_items] == [item["id"] for item in transcript_items]
    assert [item["type"] for item in live_items] == [item["type"] for item in transcript_items]
    assert [item["status"] for item in live_items] == [item["status"] for item in transcript_items]
    assert [item["role"] for item in live_items] == [item["role"] for item in transcript_items]
    assert [item["content"] for item in live_items] == [item["content"] for item in transcript_items]
    assert [item["orderSeq"] for item in live_items] == [item["orderSeq"] for item in transcript_items]

    tool_items = [item for item in live_items if item["type"] == "tool"]
    assert len(tool_items) == 1
    assert tool_items[0]["content"]["toolUseId"] == "toolu_1"
    assert tool_items[0]["content"]["kind"] == "command"
    assert tool_items[0]["content"]["command"] == "pytest -q"
    assert tool_items[0]["content"]["result"] == "249 passed"
    assert tool_items[0]["content"]["outputPreview"] == "249 passed"
    assert tool_items[0]["status"] == "done"


def test_claude_timeline_ids_are_stable_across_platform_session_ids():
    raw = [
        {
            "uuid": "evt_assistant",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:01Z",
            "message": {
                "id": "msg_assistant_1",
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll run them."},
                    {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "pytest -q"}},
                ],
            },
        },
    ]
    events = ClaudeLiveNormalizer().normalize(raw)
    reducer = ClaudeTimelineReducer()

    first = reducer.reduce(session_id="sess_live", turn_id="turn_1", events=events)
    second = reducer.reduce(session_id="sess_history", turn_id="turn_1", events=events)

    assert [item["id"] for item in first] == [item["id"] for item in second]


def test_claude_file_and_mcp_tools_reduce_to_platform_tool_content():
    raw_turn = [
        {
            "uuid": "evt_write",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:01Z",
            "message": {
                "id": "msg_assistant_1",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_write",
                        "name": "Write",
                        "input": {"file_path": "/repo/app.py", "content": "print('hi')\n"},
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_mcp",
                        "name": "mcp__browser__click",
                        "input": {"selector": "#send"},
                    },
                ],
            },
        },
        {
            "uuid": "evt_write_result",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:02Z",
            "message": {
                "id": "msg_tool_results",
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_write", "content": "File created"},
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_mcp",
                        "content": [{"type": "text", "text": "clicked"}],
                    },
                ],
            },
        },
    ]

    items = ClaudeTimelineReducer().reduce(
        session_id="sess_1",
        turn_id="turn_1",
        events=ClaudeLiveNormalizer().normalize(raw_turn),
    )

    tools = [item for item in items if item["type"] == "tool"]
    assert len(tools) == 2

    file_tool = next(item for item in tools if item["content"]["toolUseId"] == "toolu_write")
    assert file_tool["status"] == "done"
    assert file_tool["role"] == "tool"
    assert file_tool["content"]["kind"] == "file_change"
    assert file_tool["content"]["changes"] == [
        {
            "path": "/repo/app.py",
            "action": "add",
            "kind": {"type": "add"},
            "diff": "print('hi')\n",
        }
    ]
    assert file_tool["content"]["result"] == "File created"

    mcp_tool = next(item for item in tools if item["content"]["toolUseId"] == "toolu_mcp")
    assert mcp_tool["status"] == "done"
    assert mcp_tool["content"]["kind"] == "mcp"
    assert mcp_tool["content"]["server"] == "browser"
    assert mcp_tool["content"]["tool"] == "click"
    assert mcp_tool["content"]["arguments"] == {"selector": "#send"}
    assert mcp_tool["content"]["outputPreview"] == "clicked"


def test_claude_task_event_tools_are_filtered_from_live_and_transcript_timelines():
    raw_turn = [
        {
            "uuid": "evt_task_update",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:01Z",
            "message": {
                "id": "msg_task_update",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_task_1",
                        "name": "TaskUpdate",
                        "input": {
                            "taskId": "13",
                            "status": "deleted",
                            "description": "obsolete task",
                        },
                    }
                ],
            },
        },
        {
            "uuid": "evt_task_update_result",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:02Z",
            "message": {
                "id": "msg_task_update_result",
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_task_1",
                        "content": "Updated task #13 deleted",
                    }
                ],
            },
        },
        {
            "uuid": "evt_assistant",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:03Z",
            "message": {
                "id": "msg_assistant_1",
                "role": "assistant",
                "content": [{"type": "text", "text": "Done."}],
            },
        },
    ]

    reducer = ClaudeTimelineReducer()
    live_items = reducer.reduce(
        session_id="sess_1",
        turn_id="turn_1",
        events=ClaudeLiveNormalizer().normalize(raw_turn),
    )
    transcript_items = reducer.reduce(
        session_id="sess_1",
        turn_id="turn_1",
        events=ClaudeTranscriptNormalizer().normalize(raw_turn),
    )

    assert [item["content"].get("text") for item in live_items] == ["Done."]
    assert [item["content"].get("text") for item in transcript_items] == ["Done."]
    assert all(item["type"] != "tool" for item in live_items)
    assert all(item["type"] != "tool" for item in transcript_items)


def test_claude_variant_specific_tools_reduce_to_readable_cards():
    raw_turn = [
        {
            "uuid": "evt_tools",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:01Z",
            "message": {
                "id": "msg_assistant_1",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_wake",
                        "name": "ScheduleWakeup",
                        "input": {
                            "delaySeconds": 120,
                            "prompt": "检查 Windows 打包后台任务结果",
                            "reason": "等待外部构建",
                        },
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_stop",
                        "name": "TaskStop",
                        "input": {"taskId": "build-42"},
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_search",
                        "name": "ToolSearch",
                        "input": {"max_results": 3, "query": "select:TaskStop"},
                    },
                ],
            },
        },
        {
            "uuid": "evt_tools_result",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:02Z",
            "message": {
                "id": "msg_tool_results",
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_wake", "content": "Scheduled"},
                    {"type": "tool_result", "tool_use_id": "toolu_stop", "content": "Stopped build-42"},
                    {"type": "tool_result", "tool_use_id": "toolu_search", "content": "1 tool loaded"},
                ],
            },
        },
    ]

    reducer = ClaudeTimelineReducer()
    live_items = reducer.reduce(
        session_id="sess_1",
        turn_id="turn_1",
        events=ClaudeLiveNormalizer().normalize(raw_turn),
    )
    transcript_items = reducer.reduce(
        session_id="sess_1",
        turn_id="turn_1",
        events=ClaudeTranscriptNormalizer().normalize(raw_turn),
    )

    for items in (live_items, transcript_items):
        tools = [item for item in items if item["type"] == "tool"]
        assert len(tools) == 3

        wake = next(item for item in tools if item["content"]["toolUseId"] == "toolu_wake")
        assert wake["content"]["kind"] == "schedule_wakeup"
        assert wake["content"]["delaySeconds"] == 120
        assert wake["content"]["reason"] == "等待外部构建"
        assert wake["content"]["prompt"] == "检查 Windows 打包后台任务结果"

        stop = next(item for item in tools if item["content"]["toolUseId"] == "toolu_stop")
        assert stop["content"]["kind"] == "task_stop"
        assert stop["content"]["target"] == "build-42"

        search = next(item for item in tools if item["content"]["toolUseId"] == "toolu_search")
        assert search["content"]["kind"] == "tool_search"
        assert search["content"]["query"] == "select:TaskStop"
        assert search["content"]["maxResults"] == 3


def test_claude_thinking_block_reduces_to_reasoning_card_without_colliding_with_text():
    # An assistant message carrying both an extended-thinking block and the
    # visible answer text. They share the same parent message id, so the
    # reasoning item must get its own block-index-derived id instead of
    # colliding with (and overwriting) the answer message. Live transcript
    # JSONL carries the text under `thinking`; live SDK messages carry it under
    # `text` (already normalized by _blocks_to_dicts) — accept either.
    raw_turn = [
        {
            "uuid": "evt_assistant",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:01Z",
            "message": {
                "id": "msg_assistant_1",
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Let me weigh the options.", "signature": ""},
                    {"type": "text", "text": "Here's the answer."},
                ],
            },
        },
    ]

    reducer = ClaudeTimelineReducer()
    live_items = reducer.reduce(
        session_id="sess_1",
        turn_id="turn_1",
        events=ClaudeLiveNormalizer().normalize(raw_turn),
    )
    transcript_items = reducer.reduce(
        session_id="sess_1",
        turn_id="turn_1",
        events=ClaudeTranscriptNormalizer().normalize(raw_turn),
    )

    # Both paths agree, and neither drops the reasoning or the answer.
    assert [item["id"] for item in live_items] == [item["id"] for item in transcript_items]
    assert [item["content"] for item in live_items] == [item["content"] for item in transcript_items]

    reasoning = [item for item in live_items if item["content"].get("kind") == "reasoning"]
    messages = [item for item in live_items if item["type"] == "message"]
    assert len(reasoning) == 1
    assert len(messages) == 1
    # The reasoning card is a system item the clients render collapsibly.
    assert reasoning[0]["type"] == "system"
    assert reasoning[0]["role"] == "system"
    assert reasoning[0]["content"] == {"kind": "reasoning", "text": "Let me weigh the options."}
    # Distinct ids: reasoning must not overwrite the answer message.
    assert reasoning[0]["id"] != messages[0]["id"]
    assert messages[0]["content"]["text"] == "Here's the answer."


def test_claude_redacted_thinking_reduces_to_a_hidden_reasoning_card():
    # A redacted_thinking block carries no plaintext. The live path routes it
    # through _blocks_to_dicts (type "thinking" + redacted flag, empty text);
    # the transcript-replay path passes the raw JSONL straight through (type
    # "redacted_thinking", encrypted data, no prose). Both must survive as a
    # single reasoning card flagged redacted, so the client shows a "reasoning
    # hidden" placeholder instead of silently dropping it.
    live_turn = [
        {
            "uuid": "evt_assistant",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:01Z",
            "message": {
                "id": "msg_assistant_1",
                "role": "assistant",
                "content": [
                    {"type": "thinking", "text": "", "redacted": True},
                    {"type": "text", "text": "Here's the answer."},
                ],
            },
        },
    ]
    transcript_turn = [
        {
            "uuid": "evt_assistant",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:01Z",
            "message": {
                "id": "msg_assistant_1",
                "role": "assistant",
                "content": [
                    {"type": "redacted_thinking", "data": "EncRypTedBlOb=="},
                    {"type": "text", "text": "Here's the answer."},
                ],
            },
        },
    ]

    reducer = ClaudeTimelineReducer()
    live_items = reducer.reduce(
        session_id="sess_1",
        turn_id="turn_1",
        events=ClaudeLiveNormalizer().normalize(live_turn),
    )
    transcript_items = reducer.reduce(
        session_id="sess_1",
        turn_id="turn_1",
        events=ClaudeTranscriptNormalizer().normalize(transcript_turn),
    )

    # Both shapes converge on identical timeline ids and content.
    assert [item["id"] for item in live_items] == [item["id"] for item in transcript_items]
    assert [item["content"] for item in live_items] == [item["content"] for item in transcript_items]

    reasoning = [item for item in live_items if item["content"].get("kind") == "reasoning"]
    messages = [item for item in live_items if item["type"] == "message"]
    assert len(reasoning) == 1
    assert len(messages) == 1
    # The card survives, flagged redacted, with an empty body (no leaked prose).
    assert reasoning[0]["type"] == "system"
    assert reasoning[0]["content"] == {"kind": "reasoning", "text": "", "redacted": True}
    # Distinct ids: the redacted card must not overwrite the answer message.
    assert reasoning[0]["id"] != messages[0]["id"]
    assert messages[0]["content"]["text"] == "Here's the answer."


def test_claude_subagent_output_is_linked_to_parent_task_item():
    # A real Task (sub-agent) tool_use, followed by sub-agent-internal output
    # that carries parent_tool_use_id pointing back at the Task. The sub-agent
    # message and its tool call must be attributed to the parent Task's item id
    # via parentItemId, while the Task item itself has no parent.
    raw_turn = [
        {
            "uuid": "evt_task",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:01Z",
            "message": {
                "id": "msg_task",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_task_1",
                        "name": "Task",
                        "input": {"description": "investigate"},
                    }
                ],
            },
        },
        {
            "uuid": "evt_sub_text",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:02Z",
            "parent_tool_use_id": "toolu_task_1",
            "message": {
                "id": "msg_sub_text",
                "role": "assistant",
                "content": [{"type": "text", "text": "Reading files."}],
            },
        },
        {
            "uuid": "evt_sub_tool",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:03Z",
            "parent_tool_use_id": "toolu_task_1",
            "message": {
                "id": "msg_sub_tool",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_sub_bash",
                        "name": "Bash",
                        "input": {"command": "ls"},
                    }
                ],
            },
        },
    ]

    reducer = ClaudeTimelineReducer()
    for normalizer in (ClaudeLiveNormalizer(), ClaudeTranscriptNormalizer()):
        items = reducer.reduce(
            session_id="sess_1",
            turn_id="turn_1",
            events=normalizer.normalize(raw_turn),
        )
        by_source = {item["source"]["itemId"]: item for item in items}
        task_item = by_source["toolu_task_1"]
        sub_text = by_source["msg_sub_text"]
        sub_tool = by_source["toolu_sub_bash"]

        # The Task card is top-level; sub-agent output points back to its id.
        assert task_item.get("parentItemId") is None
        assert sub_text["parentItemId"] == task_item["id"]
        assert sub_tool["parentItemId"] == task_item["id"]


def test_claude_compact_boundary_reduces_to_a_separator_card():
    # The CLI writes a top-level {"type":"system","subtype":"compact_boundary",
    # "compactMetadata":{...}} record when it auto-compacts the context window.
    # It has no content array, so the old normalizer dropped it and the timeline
    # "jumped" with no explanation. It must now surface as a system separator
    # carrying the trigger and before/after token counts, identically on the
    # live and history-replay paths.
    raw_turn = [
        {
            "uuid": "evt_user",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:01Z",
            "message": {"id": "msg_user_1", "role": "user", "content": "hi"},
        },
        {
            "uuid": "evt_compact",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:02Z",
            "type": "system",
            "subtype": "compact_boundary",
            "compactMetadata": {
                "trigger": "auto",
                "preTokens": 160000,
                "postTokens": 42000,
                "cumulativeDroppedTokens": 118000,
                "durationMs": 1234,
            },
        },
        {
            "uuid": "evt_assistant",
            "session_id": "claude_sess_1",
            "timestamp": "2026-06-04T00:00:03Z",
            "message": {
                "id": "msg_assistant_1",
                "role": "assistant",
                "content": [{"type": "text", "text": "after compaction"}],
            },
        },
    ]

    reducer = ClaudeTimelineReducer()
    live_items = reducer.reduce(
        session_id="sess_1",
        turn_id="turn_1",
        events=ClaudeLiveNormalizer().normalize(raw_turn),
    )
    transcript_items = reducer.reduce(
        session_id="sess_1",
        turn_id="turn_1",
        events=ClaudeTranscriptNormalizer().normalize(raw_turn),
    )

    # Live and replay converge on the same ids and content.
    assert [item["id"] for item in live_items] == [item["id"] for item in transcript_items]
    assert [item["content"] for item in live_items] == [item["content"] for item in transcript_items]

    compact = [item for item in live_items if item["content"].get("kind") == "compact"]
    assert len(compact) == 1
    assert compact[0]["type"] == "system"
    assert compact[0]["role"] == "system"
    assert compact[0]["content"] == {
        "kind": "compact",
        "trigger": "auto",
        "preTokens": 160000,
        "postTokens": 42000,
        "droppedTokens": 118000,
    }

    # Ordering is preserved: the separator sits between the user turn and the
    # post-compaction assistant reply, with no duplication.
    kinds = [
        item["type"] if item["content"].get("kind") != "compact" else "compact"
        for item in live_items
    ]
    assert kinds == ["message", "compact", "message"]
