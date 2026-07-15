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
    # True for a redacted (encrypted) thinking block whose prose the client
    # cannot show. The reasoning card renders a placeholder instead of text.
    reasoningRedacted: bool = False
    # Set on a compact_boundary event (blockType == "compact"). Holds the CLI's
    # compactMetadata (trigger / preTokens / postTokens / ...) so the reducer can
    # emit a "context compacted: N -> M tokens" separator card.
    compactMetadata: dict[str, Any] | None = None
