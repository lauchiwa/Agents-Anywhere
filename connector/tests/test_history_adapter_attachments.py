"""Unit tests for attachment entry processing in history_adapter."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from connector.claude.history_adapter import (
    _SUPPORTED_ATTACHMENT_TYPES,
    _attachment_to_timeline_item,
    _normalize_attachment_content,
    _parse_skill_listing,
    _read_attachment_entries,
    _session_jsonl_path,
)


# ---------------------------------------------------------------------------
# _parse_skill_listing
# ---------------------------------------------------------------------------


def test_parse_skill_listing_parses_name_and_description():
    text = "- alpha: First skill\n- beta: Second skill"
    result = _parse_skill_listing(text)
    assert result == [
        {"name": "alpha", "description": "First skill"},
        {"name": "beta", "description": "Second skill"},
    ]


def test_parse_skill_listing_handles_name_only():
    text = "- gamma\n- delta: Has desc"
    result = _parse_skill_listing(text)
    assert result[0] == {"name": "gamma", "description": ""}
    assert result[1] == {"name": "delta", "description": "Has desc"}


def test_parse_skill_listing_skips_non_list_lines():
    text = "Some preamble\n- valid: yes\n\nTrailing"
    result = _parse_skill_listing(text)
    assert len(result) == 1
    assert result[0]["name"] == "valid"


def test_parse_skill_listing_empty_text():
    assert _parse_skill_listing("") == []
    assert _parse_skill_listing("   \n  ") == []


# ---------------------------------------------------------------------------
# _normalize_attachment_content
# ---------------------------------------------------------------------------


def test_normalize_attachment_content_skill_listing():
    att = {"type": "skill_listing", "content": "- foo: Bar skill\n- baz: Qux skill"}
    result = _normalize_attachment_content("skill_listing", att)
    assert result is not None
    assert result["kind"] == "skill_listing"
    assert len(result["skills"]) == 2
    assert result["skills"][0] == {"name": "foo", "description": "Bar skill"}


def test_normalize_attachment_content_skill_listing_empty_returns_none():
    att = {"type": "skill_listing", "content": ""}
    result = _normalize_attachment_content("skill_listing", att)
    assert result is None


def test_normalize_attachment_content_deferred_tools_delta():
    att = {"type": "deferred_tools_delta", "addedNames": ["ToolA", "ToolB"], "removedNames": []}
    result = _normalize_attachment_content("deferred_tools_delta", att)
    assert result is not None
    assert result["kind"] == "deferred_tools_delta"
    assert result["addedNames"] == ["ToolA", "ToolB"]
    assert result["removedNames"] == []


def test_normalize_attachment_content_deferred_tools_delta_empty_returns_none():
    att = {"type": "deferred_tools_delta", "addedNames": [], "removedNames": []}
    result = _normalize_attachment_content("deferred_tools_delta", att)
    assert result is None


def test_normalize_attachment_content_invoked_skills():
    att = {
        "type": "invoked_skills",
        "skills": [
            {"name": "trellis-check", "path": "projectSettings:trellis-check"},
        ],
    }
    result = _normalize_attachment_content("invoked_skills", att)
    assert result is not None
    assert result["kind"] == "invoked_skills"
    assert result["skills"] == [{"name": "trellis-check", "path": "projectSettings:trellis-check"}]


def test_normalize_attachment_content_invoked_skills_empty_returns_none():
    att = {"type": "invoked_skills", "skills": []}
    result = _normalize_attachment_content("invoked_skills", att)
    assert result is None


def test_normalize_attachment_content_ignores_unknown_type():
    result = _normalize_attachment_content("task_reminder", {"type": "task_reminder", "content": []})
    assert result is None
    result = _normalize_attachment_content("hook_success", {"type": "hook_success"})
    assert result is None


# ---------------------------------------------------------------------------
# _session_jsonl_path
# ---------------------------------------------------------------------------


def test_session_jsonl_path_returns_path_attr(tmp_path):
    fake_file = tmp_path / "session.jsonl"
    fake_file.write_text("")

    class FakeInfo:
        path = str(fake_file)

    assert _session_jsonl_path(FakeInfo()) == str(fake_file)


def test_session_jsonl_path_returns_none_when_no_attr():
    class NoPath:
        pass

    assert _session_jsonl_path(NoPath()) is None


def test_session_jsonl_path_returns_none_when_file_missing():
    class WithPath:
        path = "/does/not/exist.jsonl"

    assert _session_jsonl_path(WithPath()) is None


# ---------------------------------------------------------------------------
# _read_attachment_entries
# ---------------------------------------------------------------------------


def _write_jsonl(path: str, lines: list[dict]) -> None:
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def test_read_attachment_entries_returns_supported_types(tmp_path):
    jsonl = tmp_path / "s.jsonl"
    _write_jsonl(str(jsonl), [
        {
            "uuid": "u1",
            "parentUuid": "p1",
            "session_id": "sess",
            "timestamp": "2026-01-01T00:00:00Z",
            "attachment": {"type": "skill_listing", "content": "- alpha: A skill"},
        },
        {
            "uuid": "u2",
            "parentUuid": "p2",
            "session_id": "sess",
            "timestamp": "2026-01-01T00:00:01Z",
            "attachment": {"type": "deferred_tools_delta", "addedNames": ["T1"], "removedNames": []},
        },
    ])

    class Info:
        path = str(jsonl)

    entries = _read_attachment_entries(Info())
    assert len(entries) == 2
    assert entries[0]["uuid"] == "u1"
    assert entries[1]["attachment"]["type"] == "deferred_tools_delta"


def test_read_attachment_entries_filters_unsupported(tmp_path):
    jsonl = tmp_path / "s.jsonl"
    _write_jsonl(str(jsonl), [
        {"uuid": "u1", "attachment": {"type": "hook_success", "content": ""}},
        {"uuid": "u2", "attachment": {"type": "task_reminder", "content": [], "itemCount": 0}},
        {"uuid": "u3", "attachment": {"type": "skill_listing", "content": "- x: y"}},
    ])

    class Info:
        path = str(jsonl)

    entries = _read_attachment_entries(Info())
    assert len(entries) == 1
    assert entries[0]["uuid"] == "u3"


def test_read_attachment_entries_handles_missing_path():
    class NoPath:
        pass

    assert _read_attachment_entries(NoPath()) == []


def test_read_attachment_entries_handles_malformed_json(tmp_path):
    jsonl = tmp_path / "s.jsonl"
    jsonl.write_text("not json\n{valid: false}\n")

    class Info:
        path = str(jsonl)

    # Should not raise, just return empty
    entries = _read_attachment_entries(Info())
    assert entries == []


# ---------------------------------------------------------------------------
# _attachment_to_timeline_item
# ---------------------------------------------------------------------------


def test_attachment_to_timeline_item_skill_listing():
    entry = {
        "uuid": "abc123",
        "parentUuid": "parent",
        "session_id": "sess",
        "timestamp": "2026-01-01T00:00:00Z",
        "attachment": {"type": "skill_listing", "content": "- foo: Bar\n- baz: Qux"},
    }
    item = _attachment_to_timeline_item(
        entry,
        session_id="sess",
        external_session_id="ext-sess",
        turn_id="turn1",
        order_seq=5,
    )
    assert item is not None
    assert item["type"] == "system"
    assert item["content"]["kind"] == "skill_listing"
    assert item["orderSeq"] == 5
    assert item["id"] == "claude_attachment_abc123"
    assert item["turnId"] == "turn1"


def test_attachment_to_timeline_item_returns_none_for_empty():
    entry = {
        "uuid": "u1",
        "parentUuid": None,
        "session_id": "sess",
        "timestamp": "",
        "attachment": {"type": "skill_listing", "content": ""},
    }
    item = _attachment_to_timeline_item(
        entry,
        session_id="sess",
        external_session_id="ext",
        turn_id="t1",
        order_seq=1,
    )
    assert item is None
