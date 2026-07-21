from __future__ import annotations

from typing import Any

import pytest

from connector.claude.normalized import NormalizedClaudeEvent
from connector.claude.timeline_reducer import (
    ClaudeTimelineReducer,
    externalize_tool_result_images,
)


def _tool_result_event(result: Any) -> NormalizedClaudeEvent:
    return NormalizedClaudeEvent(
        claudeSessionId="cs",
        sourceEventId="ev1",
        messageId="m1",
        role="tool",
        blockIndex=0,
        blockType="tool_result",
        toolUseId="tu1",
        toolResult=result,
        timestamp="2026-07-13T16:43:34.443Z",
    )


def _reduce_one(result: Any) -> dict[str, Any]:
    reducer = ClaudeTimelineReducer()
    items = reducer.reduce(
        session_id="s",
        turn_id="t",
        events=[_tool_result_event(result)],
    )
    tool_items = [i for i in items if i.get("type") == "tool"]
    assert len(tool_items) == 1
    return tool_items[0]


def test_reduce_strips_inline_image_out_of_text_fields():
    # A tool_result carrying an inline image (the real shape: Read *.png ->
    # {"type":"image","source":{"type":"base64",...}}) must not serialize the
    # base64 into any text field; the image is staged in pendingImages instead.
    item = _reduce_one(
        [
            {"type": "text", "text": "here is the screenshot"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}},
        ]
    )
    content = item["content"]
    assert "QUJD" not in content.get("outputText", "")
    assert "QUJD" not in content.get("text", "")
    # The image is removed from the surfaced result; text block is preserved.
    assert content["result"] == [{"type": "text", "text": "here is the screenshot"}]
    assert "here is the screenshot" in content["outputText"]
    assert content["pendingImages"] == [{"mediaType": "image/png", "data": "QUJD"}]


def test_reduce_leaves_non_image_result_untouched():
    item = _reduce_one("plain text output")
    content = item["content"]
    assert content["outputText"] == "plain text output"
    assert "pendingImages" not in content


@pytest.mark.anyio
async def test_externalize_uploads_and_rewrites_pending_images():
    # The async pass decodes each staged base64 image, uploads it via the
    # injected uploader, and rewrites pendingImages into an attachments ref list
    # of {fileId,name,mediaType,size,sha256}. No base64 survives on the item.
    uploaded: list[tuple[str, bytes, str, str]] = []

    async def uploader(session_id: str, data: bytes, name: str, media_type: str) -> dict[str, Any]:
        uploaded.append((session_id, data, name, media_type))
        return {
            "fileId": "file_abc123",
            "name": name,
            "mediaType": media_type,
            "size": len(data),
            "sha256": "deadbeef",
        }

    item = _reduce_one(
        [
            {"type": "text", "text": "shot"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}},
        ]
    )
    items = [item]
    await externalize_tool_result_images(items, session_id="s", uploader=uploader)

    content = items[0]["content"]
    assert "pendingImages" not in content
    attachments = content["attachments"]
    assert len(attachments) == 1
    ref = attachments[0]
    assert ref["fileId"] == "file_abc123"
    assert ref["mediaType"] == "image/png"
    assert ref["sha256"] == "deadbeef"
    # The uploader received the decoded bytes (base64 "QUJD" -> b"ABC").
    assert len(uploaded) == 1
    assert uploaded[0][1] == b"ABC"
    assert uploaded[0][3] == "image/png"


@pytest.mark.anyio
async def test_externalize_without_uploader_drops_bytes_with_marker():
    # No uploader wired: the staged bytes must be dropped (never leaked back onto
    # the timeline) and replaced with an unresolved marker rather than crashing.
    item = _reduce_one(
        [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}},
        ]
    )
    items = [item]
    await externalize_tool_result_images(items, session_id="s", uploader=None)

    content = items[0]["content"]
    assert "pendingImages" not in content
    assert "QUJD" not in str(content)
    attachments = content["attachments"]
    assert attachments == [{"unresolved": True, "mediaType": "image/jpeg"}]


@pytest.mark.anyio
async def test_externalize_upload_failure_falls_back_to_marker():
    # Upload raising must degrade to an unresolved marker, not propagate.
    async def failing_uploader(session_id: str, data: bytes, name: str, media_type: str) -> dict[str, Any]:
        raise RuntimeError("network down")

    item = _reduce_one(
        [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}},
        ]
    )
    items = [item]
    await externalize_tool_result_images(items, session_id="s", uploader=failing_uploader)

    content = items[0]["content"]
    assert content["attachments"] == [{"unresolved": True, "mediaType": "image/png"}]
