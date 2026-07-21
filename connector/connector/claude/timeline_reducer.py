from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Awaitable, Callable
from typing import Any

from connector.claude.normalized import NormalizedClaudeEvent
from connector.claude.timeline_identity import ClaudeTimelineIdentity, content_hash
from connector.logging import logger


# (session_id, data, name, media_type) -> stored metadata {fileId,name,mediaType,size,sha256}.
AttachmentUploader = Callable[[str, bytes, str, str], Awaitable[dict[str, Any]]]


class ClaudeTimelineReducer:
    def reduce(
        self,
        *,
        session_id: str,
        turn_id: str,
        events: list[NormalizedClaudeEvent],
    ) -> list[dict[str, Any]]:
        items: dict[str, dict[str, Any]] = {}
        ignored_tool_use_ids: set[str] = set()
        order_seq = 1
        for event in events:
            if event.toolUseId and event.toolResult is None and is_task_event_tool_name(event.toolName):
                ignored_tool_use_ids.add(event.toolUseId)
                continue
            if event.toolUseId and event.toolResult is not None and event.toolUseId in ignored_tool_use_ids:
                continue
            item = self._reduce_event(session_id=session_id, turn_id=turn_id, event=event, order_seq=order_seq)
            if item is None:
                continue
            existing = items.get(item["id"])
            if existing is None:
                items[item["id"]] = item
                order_seq += 1
                continue
            items[item["id"]] = _merge_item(existing, item)
        return sorted(items.values(), key=lambda item: int(item.get("orderSeq") or 0))

    def _reduce_event(
        self,
        *,
        session_id: str,
        turn_id: str,
        event: NormalizedClaudeEvent,
        order_seq: int,
    ) -> dict[str, Any] | None:
        message_id = event.messageId or event.sourceEventId
        # If this event came from inside a sub-agent (Task tool), resolve the
        # parent Task's tool_use_id to the timeline item id of that Task card,
        # so the client can nest sub-agent output under it. Uses the same
        # identity derivation as the Task tool_call item itself.
        parent_item_id: str | None = None
        if event.parentToolUseId:
            parent_item_id = ClaudeTimelineIdentity.tool_call(
                session_id=session_id,
                claude_session_id=event.claudeSessionId,
                tool_use_id=event.parentToolUseId,
            )
        if event.toolUseId and event.toolResult is not None:
            item_id = ClaudeTimelineIdentity.tool_result(
                session_id=session_id,
                claude_session_id=event.claudeSessionId,
                tool_use_id=event.toolUseId,
            )
            content = _tool_result_content(event)
            status = "failed" if event.toolResultIsError else "done"
            return {
                "id": item_id,
                "sessionId": session_id,
                "turnId": turn_id,
                "type": "tool",
                "status": status,
                "role": "tool",
                "parentItemId": parent_item_id,
                "content": content,
                "source": _source(event, turn_id, "tool_result"),
                "orderSeq": order_seq,
                "revision": 1,
                "contentHash": content_hash(content),
                "createdAt": event.timestamp,
                "updatedAt": event.timestamp,
                "completedAt": event.timestamp,
            }

        if event.toolUseId:
            item_id = ClaudeTimelineIdentity.tool_call(
                session_id=session_id,
                claude_session_id=event.claudeSessionId,
                tool_use_id=event.toolUseId,
            )
            content = _tool_call_content(event)
            return {
                "id": item_id,
                "sessionId": session_id,
                "turnId": turn_id,
                "type": "tool",
                "status": "running",
                "role": "tool",
                "parentItemId": parent_item_id,
                "content": content,
                "source": _source(event, turn_id, "tool_use"),
                "orderSeq": order_seq,
                "revision": 1,
                "contentHash": content_hash(content),
                "createdAt": event.timestamp,
                "updatedAt": event.timestamp,
            }

        if event.blockType == "thinking" and (
            (event.text is not None and event.text.strip()) or event.reasoningRedacted
        ):
            # Thinking blocks render as a collapsible "reasoning" system card on
            # every client. They ride inside the assistant message but must not
            # share its timeline id, so they use a dedicated reasoning identity
            # keyed by block index (see ClaudeTimelineIdentity.reasoning).
            #
            # redacted_thinking has no plaintext: it arrives with empty text and
            # reasoningRedacted=True. It still gets a card (so the user knows the
            # model reasoned) but carries a redacted flag for a placeholder body.
            item_id = ClaudeTimelineIdentity.reasoning(
                session_id=session_id,
                claude_session_id=event.claudeSessionId,
                message_id=message_id,
                block_index=event.blockIndex,
            )
            content: dict[str, Any] = {"kind": "reasoning", "text": event.text or ""}
            if event.reasoningRedacted:
                content["redacted"] = True
            return {
                "id": item_id,
                "sessionId": session_id,
                "turnId": turn_id,
                "type": "system",
                "status": "done",
                "role": "system",
                "parentItemId": parent_item_id,
                "content": content,
                "source": _source(event, turn_id, "reasoning"),
                "orderSeq": order_seq,
                "revision": 1,
                "contentHash": content_hash(content),
                "createdAt": event.timestamp,
                "updatedAt": event.timestamp,
                "completedAt": event.timestamp,
            }

        if event.blockType == "compact":
            # Context-compaction boundary: the CLI dropped earlier history to
            # reclaim the window. Render as a non-expandable separator so the
            # user understands why a chunk of the conversation vanished. Keyed by
            # the source event id (the compact record's own uuid) so the live and
            # replay paths converge on the same timeline id.
            item_id = ClaudeTimelineIdentity.compact(
                session_id=session_id,
                claude_session_id=event.claudeSessionId,
                source_event_id=event.sourceEventId,
            )
            content = _compact_content(event)
            return {
                "id": item_id,
                "sessionId": session_id,
                "turnId": turn_id,
                "type": "system",
                "status": "done",
                "role": "system",
                "parentItemId": parent_item_id,
                "content": content,
                "source": _source(event, turn_id, "compact"),
                "orderSeq": order_seq,
                "revision": 1,
                "contentHash": content_hash(content),
                "createdAt": event.timestamp,
                "updatedAt": event.timestamp,
                "completedAt": event.timestamp,
            }

        if event.role in {"user", "assistant", "system"} and event.text is not None and event.text.strip():
            item_id = ClaudeTimelineIdentity.message(
                session_id=session_id,
                claude_session_id=event.claudeSessionId,
                message_id=message_id,
            )
            content = {"text": event.text}
            if event.attachments:
                content["attachments"] = event.attachments
            source = _source(event, turn_id, "message")
            if event.clientMessageId:
                source["clientMessageId"] = event.clientMessageId
            return {
                "id": item_id,
                "sessionId": session_id,
                "turnId": turn_id,
                "type": "message",
                "status": "done",
                "role": event.role,
                "parentItemId": parent_item_id,
                "content": content,
                "source": source,
                "orderSeq": order_seq,
                "revision": 1,
                "contentHash": content_hash(content),
                "createdAt": event.timestamp,
                "updatedAt": event.timestamp,
                "completedAt": event.timestamp,
            }
        return None


def _source(event: NormalizedClaudeEvent, turn_id: str, derived_key: str) -> dict[str, Any]:
    return {
        "runtime": "claude",
        "sessionId": event.claudeSessionId,
        "turnId": turn_id,
        "itemId": event.toolUseId or event.messageId or event.sourceEventId,
        "itemType": event.blockType,
        "event": event.sourceEventId,
        "derivedKey": derived_key,
    }


def _tool_kind(tool_name: str | None) -> str:
    if _mcp_parts(tool_name) is not None:
        return "mcp"
    if tool_name in {"Edit", "Write", "NotebookEdit"}:
        return "file_change"
    if tool_name == "MultiEdit":
        return "file_change"
    if tool_name == "Bash":
        return "command"
    if tool_name in {"WebFetch", "WebSearch"}:
        return "web_search"
    if tool_name == "ScheduleWakeup":
        return "schedule_wakeup"
    if tool_name == "TaskStop":
        return "task_stop"
    if tool_name == "ToolSearch":
        return "tool_search"
    return "tool"


def is_task_event_tool_name(tool_name: str | None) -> bool:
    """Claude Code task bookkeeping tools should not become user-visible tools.

    Keep the real Claude sub-agent tool named exactly "Task"; hide status/event
    tools such as TaskCreate and TaskUpdate. "TaskStop" is a real user-facing
    tool (it stops a running sub-agent), so it must stay visible even though it
    matches the "Task" + uppercase-5th-char shape of the bookkeeping heuristic.
    """
    if tool_name in _VISIBLE_TASK_TOOL_NAMES:
        return False
    return bool(tool_name and tool_name.startswith("Task") and len(tool_name) > 4 and tool_name[4].isupper())


_VISIBLE_TASK_TOOL_NAMES = {"Task", "TaskStop"}


def _merge_item(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if existing.get("type") == "tool" and incoming.get("status") in {"done", "failed", "interrupted", "cancelled"}:
        data = dict(existing)
        content = dict(data.get("content") or {})
        incoming_content = incoming.get("content")
        content.update(incoming_content if isinstance(incoming_content, dict) else {})
        data["content"] = content
        data["status"] = incoming.get("status")
        data["role"] = incoming.get("role") or data.get("role")
        data["revision"] = int(data.get("revision") or 1) + 1
        data["contentHash"] = content_hash(content)
        data["updatedAt"] = incoming.get("updatedAt")
        data["completedAt"] = incoming.get("completedAt")
        return data
    if _content_score(incoming.get("content")) > _content_score(existing.get("content")):
        return incoming
    return existing


def _content_score(content: Any) -> int:
    return len(str(content or ""))


def _tool_call_content(event: NormalizedClaudeEvent) -> dict[str, Any]:
    tool_name = event.toolName or "tool"
    tool_input = event.toolInput if isinstance(event.toolInput, dict) else event.toolInput
    common = _tool_common(event)
    kind = _tool_kind(tool_name)
    if kind == "command":
        input_data = tool_input if isinstance(tool_input, dict) else {}
        command = _string(input_data.get("command") or input_data.get("cmd")) or ""
        content = {
            **common,
            "kind": "command",
            "command": command,
            "description": _string(input_data.get("description")) or command,
            "cwd": _string(input_data.get("cwd")),
        }
        if isinstance(input_data.get("run_in_background"), bool):
            content["runInBackground"] = input_data.get("run_in_background")
        return _strip_empty(content)

    if kind == "file_change":
        return _strip_empty({
            **common,
            "kind": "file_change",
            "changes": _file_changes(tool_name, tool_input),
        })

    if kind == "web_search":
        input_data = tool_input if isinstance(tool_input, dict) else {}
        return _strip_empty({
            **common,
            "kind": "web_search",
            "query": _string(input_data.get("query")),
            "url": _string(input_data.get("url")),
            "action": input_data,
        })

    if kind == "schedule_wakeup":
        input_data = tool_input if isinstance(tool_input, dict) else {}
        return _strip_empty({
            **common,
            "kind": "schedule_wakeup",
            "delaySeconds": _int(input_data.get("delaySeconds")),
            "reason": _string(input_data.get("reason")),
            "prompt": _string(input_data.get("prompt")),
        })

    if kind == "task_stop":
        input_data = tool_input if isinstance(tool_input, dict) else {}
        return _strip_empty({
            **common,
            "kind": "task_stop",
            "target": _string(input_data.get("taskId"))
            or _string(input_data.get("id"))
            or _string(input_data.get("name")),
        })

    if kind == "tool_search":
        input_data = tool_input if isinstance(tool_input, dict) else {}
        return _strip_empty({
            **common,
            "kind": "tool_search",
            "query": _string(input_data.get("query")),
            "maxResults": _int(input_data.get("max_results")),
        })

    mcp = _mcp_parts(tool_name)
    if mcp is not None:
        server, tool = mcp
        return _strip_empty({
            **common,
            "kind": "mcp",
            "server": server,
            "tool": tool,
            "arguments": tool_input if isinstance(tool_input, dict) else {},
            "result": None,
            "error": None,
        })

    return _strip_empty({
        **common,
        "kind": "tool",
        "name": tool_name,
        "tool": tool_name,
        "arguments": tool_input if isinstance(tool_input, dict) else tool_input,
    })


def _tool_result_content(event: NormalizedClaudeEvent) -> dict[str, Any]:
    # Split any inline image sub-blocks out of the tool_result before building
    # the timeline content. A single screenshot is ~500KB of base64; left in
    # `result` (and re-serialized into `outputText` by _result_text) it would
    # bloat the timeline item to >1MB and get pushed on every full SSE frame.
    # The stripped result keeps only the non-image blocks; the images ride in
    # `pendingImages` (a connector-internal staging field) until the async
    # externalizer uploads them and rewrites them into `attachments` refs.
    stripped_result, pending_images = _split_tool_result_images(event.toolResult)
    text = _result_text(stripped_result)
    content: dict[str, Any] = {
        "toolUseId": event.toolUseId,
        "result": stripped_result,
        "text": text,
        "outputText": text,
        "outputPreview": _preview_text(text),
        "outputLength": len(text),
    }
    if pending_images:
        content["pendingImages"] = pending_images
    if event.toolResultIsError:
        content["isError"] = True
        content["error"] = text
    return content


def _split_tool_result_images(result: Any) -> tuple[Any, list[dict[str, Any]]]:
    """Separate inline image sub-blocks from a tool_result's content.

    Returns (stripped_result, pending_images). `stripped_result` is `result`
    with every `{"type":"image",...}` block removed (other blocks preserved,
    order intact); `pending_images` is the list of extracted image blocks in the
    shape {"mediaType","data"} (base64 string). When `result` carries no image
    blocks the original object is returned unchanged with an empty list, so
    non-image tool results are untouched.
    """
    if not isinstance(result, list):
        return result, []
    pending: list[dict[str, Any]] = []
    kept: list[Any] = []
    for block in result:
        if isinstance(block, dict) and block.get("type") == "image":
            source = block.get("source")
            if isinstance(source, dict) and source.get("type") == "base64":
                data = source.get("data")
                media_type = source.get("media_type") or source.get("mediaType")
                if isinstance(data, str) and data:
                    pending.append(
                        {
                            "mediaType": media_type if isinstance(media_type, str) else "",
                            "data": data,
                        }
                    )
                    continue
            # An image block we can't externalize (missing/unknown source):
            # drop the raw bytes rather than leak them into the timeline, but
            # leave a lightweight marker so the block isn't silently lost.
            kept.append({"type": "image", "unresolved": True})
            continue
        kept.append(block)
    if not pending:
        return result, []
    return kept, pending


def _tool_common(event: NormalizedClaudeEvent) -> dict[str, Any]:
    return {
        "toolUseId": event.toolUseId,
        "toolName": event.toolName,
        "input": event.toolInput,
    }


def _compact_content(event: NormalizedClaudeEvent) -> dict[str, Any]:
    # A "context compacted" separator. The client renders a non-expandable
    # divider ("context compacted: N -> M tokens"); the raw compactMetadata
    # rides along so richer clients can surface the trigger/dropped counts.
    metadata = event.compactMetadata if isinstance(event.compactMetadata, dict) else {}
    content: dict[str, Any] = {"kind": "compact"}
    trigger = _string(metadata.get("trigger"))
    if trigger is not None:
        content["trigger"] = trigger
    pre_tokens = _int(metadata.get("preTokens"))
    if pre_tokens is not None:
        content["preTokens"] = pre_tokens
    post_tokens = _int(metadata.get("postTokens"))
    if post_tokens is not None:
        content["postTokens"] = post_tokens
    dropped = _int(metadata.get("cumulativeDroppedTokens"))
    if dropped is not None:
        content["droppedTokens"] = dropped
    return content


def _file_changes(tool_name: str, tool_input: Any) -> list[dict[str, Any]]:
    input_data = tool_input if isinstance(tool_input, dict) else {}
    if tool_name == "Write":
        path = _string(input_data.get("file_path") or input_data.get("path")) or ""
        text = _string(input_data.get("content")) or ""
        return [_strip_empty({
            "path": path,
            "action": "add",
            "kind": {"type": "add"},
            "diff": text,
        })]
    if tool_name == "Edit":
        path = _string(input_data.get("file_path") or input_data.get("path")) or ""
        return [_strip_empty({
            "path": path,
            "action": "update",
            "kind": {"type": "update"},
            "diff": _edit_diff(
                path,
                _string(input_data.get("old_string")) or "",
                _string(input_data.get("new_string")) or "",
            ),
        })]
    if tool_name == "MultiEdit":
        path = _string(input_data.get("file_path") or input_data.get("path")) or ""
        edits = input_data.get("edits")
        if not isinstance(edits, list):
            edits = []
        diff_parts = []
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            diff_parts.append(
                _edit_diff(
                    path,
                    _string(edit.get("old_string")) or "",
                    _string(edit.get("new_string")) or "",
                    include_header=not diff_parts,
                )
            )
        return [_strip_empty({
            "path": path,
            "action": "update",
            "kind": {"type": "update"},
            "diff": "\n".join(part for part in diff_parts if part),
        })]
    if tool_name == "NotebookEdit":
        path = _string(input_data.get("notebook_path") or input_data.get("file_path") or input_data.get("path")) or ""
        new_source = _string(input_data.get("new_source")) or _json_text(input_data.get("new_source"))
        return [_strip_empty({
            "path": path,
            "action": "update",
            "kind": {"type": "update"},
            "diff": _edit_diff(path, "", new_source),
        })]
    path = _string(input_data.get("file_path") or input_data.get("path")) or ""
    return [_strip_empty({"path": path, "action": "update", "kind": {"type": "update"}})]


def _edit_diff(path: str, old: str, new: str, *, include_header: bool = True) -> str:
    lines: list[str] = []
    if include_header:
        lines.extend([f"--- {path}", f"+++ {path}"])
    lines.append("@@")
    if old:
        lines.extend(f"-{line}" for line in old.splitlines())
    if new:
        lines.extend(f"+{line}" for line in new.splitlines())
    return "\n".join(lines)


def _mcp_parts(tool_name: str | None) -> tuple[str, str] | None:
    if not tool_name or not tool_name.startswith("mcp__"):
        return None
    parts = tool_name.split("__", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def _result_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts: list[str] = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"])
            elif isinstance(item, str):
                texts.append(item)
        if texts:
            return "\n".join(texts)
    if value is None:
        return ""
    return _json_text(value)


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except TypeError:
        return str(value)


def _preview_text(value: str, limit: int = 4000) -> str:
    return value[-limit:]


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _int(value: Any) -> int | None:
    # bool is an int subclass; reject it so a stray True/False in the metadata
    # never masquerades as a token count.
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _strip_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


async def externalize_tool_result_images(
    items: list[dict[str, Any]],
    *,
    session_id: str,
    uploader: AttachmentUploader | None,
) -> None:
    """Upload the inline images staged on tool items and rewrite them as refs.

    Reducer output stages extracted tool_result images in `content.pendingImages`
    (base64) so the reduce pass stays synchronous. This async pass — called from
    both the live emit path and the transcript sync path — decodes each staged
    image, uploads the bytes via `uploader`, and replaces `pendingImages` with an
    `attachments` list of {fileId,name,mediaType,size,sha256} refs. Items are
    mutated in place; contentHash is recomputed so it reflects the rewritten
    content. On any failure (no uploader wired, decode error, upload error) the
    staged bytes are dropped and a marker attachment records the failure rather
    than leaking base64 back onto the timeline or crashing the sync.
    """
    for item in items:
        content = item.get("content")
        if not isinstance(content, dict):
            continue
        pending = content.pop("pendingImages", None)
        if not pending:
            continue
        attachments: list[dict[str, Any]] = []
        for index, image in enumerate(pending):
            if not isinstance(image, dict):
                continue
            media_type = image.get("mediaType") if isinstance(image.get("mediaType"), str) else ""
            b64 = image.get("data")
            ref = await _upload_one_image(
                session_id=session_id,
                uploader=uploader,
                media_type=media_type,
                b64=b64 if isinstance(b64, str) else None,
                index=index,
            )
            if ref is not None:
                attachments.append(ref)
        if attachments:
            existing = content.get("attachments")
            if isinstance(existing, list):
                content["attachments"] = [*existing, *attachments]
            else:
                content["attachments"] = attachments
        item["contentHash"] = content_hash(content)


async def _upload_one_image(
    *,
    session_id: str,
    uploader: AttachmentUploader | None,
    media_type: str,
    b64: str | None,
    index: int,
) -> dict[str, Any] | None:
    if uploader is None:
        logger.warning("tool_result image dropped — no attachment uploader wired session_id={}", session_id)
        return {"unresolved": True, "mediaType": media_type}
    if not b64:
        return {"unresolved": True, "mediaType": media_type}
    try:
        data = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        logger.warning("tool_result image dropped — base64 decode failed session_id={}", session_id)
        return {"unresolved": True, "mediaType": media_type}
    name = _image_name(media_type, index)
    try:
        metadata = await uploader(session_id, data, name, media_type or "application/octet-stream")
    except Exception:
        logger.exception("tool_result image upload failed session_id={}", session_id)
        return {"unresolved": True, "mediaType": media_type}
    file_id = metadata.get("fileId") if isinstance(metadata, dict) else None
    if not isinstance(file_id, str) or not file_id:
        return {"unresolved": True, "mediaType": media_type}
    ref: dict[str, Any] = {"fileId": file_id}
    for key in ("name", "mediaType", "size", "sha256"):
        value = metadata.get(key)
        if value is not None:
            ref[key] = value
    ref.setdefault("mediaType", media_type)
    return ref


def _image_name(media_type: str, index: int) -> str:
    ext = ""
    if isinstance(media_type, str) and "/" in media_type:
        ext = media_type.split("/", 1)[1].split("+", 1)[0]
    ext = ext or "img"
    return f"tool-image-{index + 1}.{ext}"
