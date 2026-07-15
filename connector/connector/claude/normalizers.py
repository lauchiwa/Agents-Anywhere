from __future__ import annotations

from typing import Any

from connector.claude.normalized import NormalizedClaudeEvent


class ClaudeLiveNormalizer:
    def normalize(self, raw_events: list[dict[str, Any]]) -> list[NormalizedClaudeEvent]:
        return [_event for raw in raw_events for _event in _normalize_raw(raw)]


class ClaudeTranscriptNormalizer:
    def normalize(self, raw_entries: list[dict[str, Any]]) -> list[NormalizedClaudeEvent]:
        return [_event for raw in raw_entries for _event in _normalize_raw(raw)]


def _normalize_raw(raw: dict[str, Any]) -> list[NormalizedClaudeEvent]:
    message = raw.get("message") if isinstance(raw.get("message"), dict) else raw
    claude_session_id = _string(raw.get("session_id") or raw.get("sessionId") or raw.get("uuid")) or "unknown"
    source_event_id = _string(raw.get("uuid") or raw.get("id") or message.get("id")) or "unknown"
    message_id = _string(message.get("id") or raw.get("message_id") or raw.get("messageId"))
    role = _string(message.get("role") or raw.get("role"))
    timestamp = _string(raw.get("timestamp") or message.get("timestamp"))
    # Sub-agent (Task tool) output carries the parent Task's tool_use_id so the
    # timeline can attribute it to that call. It lives on the raw envelope next
    # to uuid/session_id; the SDK also exposes it under camelCase in some paths.
    parent_tool_use_id = _string(raw.get("parent_tool_use_id") or raw.get("parentToolUseId"))
    # Context-compaction boundary. The CLI writes a top-level
    # {"type":"system","subtype":"compact_boundary","compactMetadata":{...}}
    # record (no content blocks) when it drops earlier history to reclaim the
    # context window. Without this branch it falls through to the empty-content
    # return below and the timeline just silently loses a chunk of history.
    # Emit a dedicated compact event so the reducer can render a separator.
    if _string(raw.get("subtype")) == "compact_boundary" or _string(message.get("subtype")) == "compact_boundary":
        compact_metadata = raw.get("compactMetadata")
        if not isinstance(compact_metadata, dict):
            compact_metadata = message.get("compactMetadata")
        return [
            NormalizedClaudeEvent(
                claudeSessionId=claude_session_id,
                sourceEventId=source_event_id,
                messageId=message_id,
                role="system",
                blockIndex=0,
                blockType="compact",
                compactMetadata=compact_metadata if isinstance(compact_metadata, dict) else {},
                timestamp=timestamp,
            )
        ]
    content = message.get("content")
    if not isinstance(content, list):
        if isinstance(content, str):
            return [
                NormalizedClaudeEvent(
                    claudeSessionId=claude_session_id,
                    sourceEventId=source_event_id,
                    messageId=message_id,
                    role=role if role in {"user", "assistant", "tool", "system"} else None,
                    blockIndex=0,
                    blockType="text",
                    text=content,
                    timestamp=timestamp,
                    parentToolUseId=parent_tool_use_id,
                )
            ]
        return []

    normalized: list[NormalizedClaudeEvent] = []
    for index, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        block_type = _string(block.get("type")) or "unknown"
        if block_type == "text":
            text = _string(block.get("text"))
            if text is not None and text.strip():
                normalized.append(
                    NormalizedClaudeEvent(
                        claudeSessionId=claude_session_id,
                        sourceEventId=f"{source_event_id}:{index}",
                        messageId=message_id,
                        role=role if role in {"user", "assistant", "tool", "system"} else None,
                        blockIndex=index,
                        blockType=block_type,
                        text=text,
                        timestamp=timestamp,
                        parentToolUseId=parent_tool_use_id,
                    )
                )
        elif block_type in {"thinking", "redacted_thinking"}:
            # Extended-thinking block. In live SDK messages the text rides in
            # `text` (normalized by _blocks_to_dicts); in raw transcript JSONL it
            # rides in `thinking`. Accept either. Rendered client-side as a
            # collapsible reasoning card (content.kind == "reasoning").
            #
            # A redacted_thinking block (encrypted by the safety system) carries
            # no plaintext. Two shapes reach here: the live path routes through
            # _blocks_to_dicts, which rewrites it to type "thinking" + a
            # `redacted` flag with empty text; the transcript-replay path passes
            # the raw JSONL block straight through, keeping type
            # "redacted_thinking". Treat either signal as redacted so the block
            # survives with an empty text and the flag, and the client renders a
            # "reasoning hidden" placeholder instead of dropping it silently.
            redacted = _bool(block.get("redacted")) or block_type == "redacted_thinking"
            text = _string(block.get("thinking")) or _string(block.get("text"))
            if redacted:
                normalized.append(
                    NormalizedClaudeEvent(
                        claudeSessionId=claude_session_id,
                        sourceEventId=f"{source_event_id}:{index}",
                        messageId=message_id,
                        role="system",
                        blockIndex=index,
                        blockType="thinking",
                        text=text or "",
                        reasoningRedacted=True,
                        timestamp=timestamp,
                        parentToolUseId=parent_tool_use_id,
                    )
                )
            elif text is not None and text.strip():
                normalized.append(
                    NormalizedClaudeEvent(
                        claudeSessionId=claude_session_id,
                        sourceEventId=f"{source_event_id}:{index}",
                        messageId=message_id,
                        role="system",
                        blockIndex=index,
                        blockType=block_type,
                        text=text,
                        timestamp=timestamp,
                        parentToolUseId=parent_tool_use_id,
                    )
                )
        elif block_type == "tool_use":
            normalized.append(
                NormalizedClaudeEvent(
                    claudeSessionId=claude_session_id,
                    sourceEventId=f"{source_event_id}:{index}",
                    messageId=message_id,
                    role="assistant",
                    blockIndex=index,
                    blockType=block_type,
                    toolUseId=_string(block.get("id")),
                    toolName=_string(block.get("name")),
                    toolInput=block.get("input"),
                    timestamp=timestamp,
                    parentToolUseId=parent_tool_use_id,
                )
            )
        elif block_type == "tool_result":
            normalized.append(
                NormalizedClaudeEvent(
                    claudeSessionId=claude_session_id,
                    sourceEventId=f"{source_event_id}:{index}",
                    messageId=message_id,
                    role="tool",
                    blockIndex=index,
                    blockType=block_type,
                    toolUseId=_string(block.get("tool_use_id")),
                    toolResult=block.get("content"),
                    toolResultIsError=block.get("is_error") if isinstance(block.get("is_error"), bool) else None,
                    text=_string(block.get("content")),
                    timestamp=timestamp,
                    parentToolUseId=parent_tool_use_id,
                )
            )
    return normalized


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _bool(value: Any) -> bool:
    return value is True
