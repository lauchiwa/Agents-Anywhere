from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(slots=True)
class NormalizedClaudeEvent:
    claudeSessionId: str
    sourceEventId: str
    messageId: str | None = None
    role: Literal["user", "assistant", "tool", "system"] | None = None
    blockIndex: int | None = None
    blockType: str | None = None
    text: str | None = None
    toolUseId: str | None = None
    toolName: str | None = None
    toolInput: Any = None
    toolResult: Any = None
    toolResultIsError: bool | None = None
    timestamp: str | None = None
    clientMessageId: str | None = None
    attachments: list[dict[str, Any]] | None = None
    # Set on events that originate inside a sub-agent (Claude "Task" tool). It
    # holds the tool_use_id of the parent Task call, so the timeline can group
    # a sub-agent's live output under the Task card that spawned it instead of
    # letting it leak into the main conversation.
    parentToolUseId: str | None = None
