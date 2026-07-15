from __future__ import annotations

import hashlib
import json
from typing import Any


class ClaudeTimelineIdentity:
    @staticmethod
    def message(*, session_id: str, claude_session_id: str, message_id: str) -> str:
        return f"claude_msg_{_short('message', claude_session_id, message_id)}"

    @staticmethod
    def tool_call(
        *,
        session_id: str,
        claude_session_id: str,
        tool_use_id: str,
    ) -> str:
        return f"claude_tool_{_short('tool', claude_session_id, tool_use_id)}"

    @staticmethod
    def tool_result(
        *,
        session_id: str,
        claude_session_id: str,
        tool_use_id: str,
    ) -> str:
        return ClaudeTimelineIdentity.tool_call(
            session_id=session_id,
            claude_session_id=claude_session_id,
            tool_use_id=tool_use_id,
        )

    @staticmethod
    def reasoning(
        *,
        session_id: str,
        claude_session_id: str,
        message_id: str,
        block_index: int | None,
    ) -> str:
        # Thinking blocks share their parent assistant message's id with the
        # visible text blocks, so a message-derived id would collide and let the
        # reasoning item overwrite (or be overwritten by) the answer text. Fold
        # the block index in to give each reasoning block its own stable id
        # across both the live and history-replay paths.
        return f"claude_reasoning_{_short('reasoning', claude_session_id, message_id, block_index)}"

    @staticmethod
    def compact(*, session_id: str, claude_session_id: str, source_event_id: str) -> str:
        # A compact_boundary record marks where the CLI auto-compacted the
        # context window. It has no message/tool id, so key the timeline item on
        # the record's own uuid (sourceEventId) — stable across the live and
        # history-replay paths, and unique per boundary so multiple compactions
        # in one session each get their own separator.
        return f"claude_compact_{_short('compact', claude_session_id, source_event_id)}"

    @staticmethod
    def derived(*values: Any) -> str:
        return f"claude_derived_{_short(*values)}"


def content_hash(*values: Any) -> str:
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _short(*values: Any) -> str:
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
