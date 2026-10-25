"""Minimal, offline-safe MCP adapter entry points for the DX2 clients.

These adapters normalize client naming only. They perform no transport, I/O,
credential lookup, Actor creation, or retries; parsing and acceptance live in
``mcp_parse``.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from . import mcp_parse


def _run(response: Mapping[str, Any], expected_run_id: str | None = None):
    return mcp_parse.run_metadata(
        response,
        expected_run_id=expected_run_id,
        expected_build_number=mcp_parse.EXPECTED_BUILD_NUMBER,
        expected_build_id=mcp_parse.EXPECTED_BUILD_ID,
    )


def _dataset(response: Mapping[str, Any], expected_dataset_id: str, expected_run_item_count: int | None = None):
    return mcp_parse.dataset_items(
        response,
        expected_dataset_id=expected_dataset_id,
        expected_run_item_count=expected_run_item_count,
    )


def _accept(run, page, expected_shortcodes: Sequence[str]):
    return mcp_parse.acceptance(
        run,
        page,
        expected_shortcodes,
        expected_build_number=mcp_parse.EXPECTED_BUILD_NUMBER,
        expected_build_id=mcp_parse.EXPECTED_BUILD_ID,
    )


# L2 one-shot adapter.
def l2_run(response: Mapping[str, Any], expected_run_id: str | None = None):
    return _run(response, expected_run_id)


def l2_dataset(response: Mapping[str, Any], expected_dataset_id: str, expected_run_item_count: int | None = None):
    return _dataset(response, expected_dataset_id, expected_run_item_count)


def l2_classify(run, page, expected_shortcodes: Sequence[str]):
    return _accept(run, page, expected_shortcodes)


# L2 recovery adapter.
def l2_recovery_run(response: Mapping[str, Any], expected_run_id: str | None = None):
    return _run(response, expected_run_id)


def l2_recovery_dataset(response: Mapping[str, Any], expected_dataset_id: str, expected_run_item_count: int | None = None):
    return _dataset(response, expected_dataset_id, expected_run_item_count)


def l2_recovery_classify(run, page, expected_shortcodes: Sequence[str]):
    return _accept(run, page, expected_shortcodes)


# L3-A bulk adapter.
def l3a_bulk_run(response: Mapping[str, Any], expected_run_id: str | None = None):
    return _run(response, expected_run_id)


def l3a_bulk_run_id(response: Mapping[str, Any], expected_run_id: str | None = None) -> str:
    return mcp_parse.extract_run_identity(response, expected_run_id=expected_run_id)


def l3a_bulk_dataset(response: Mapping[str, Any], expected_dataset_id: str, expected_run_item_count: int | None = None):
    return _dataset(response, expected_dataset_id, expected_run_item_count)


def l3a_bulk_classify(run, page, expected_shortcodes: Sequence[str]):
    return _accept(run, page, expected_shortcodes)


# L3-A recovery adapter.
def l3a_recovery_run(response: Mapping[str, Any], expected_run_id: str | None = None):
    return _run(response, expected_run_id)


def l3a_recovery_dataset(response: Mapping[str, Any], expected_dataset_id: str, expected_run_item_count: int | None = None):
    return _dataset(response, expected_dataset_id, expected_run_item_count)


def l3a_recovery_classify(run, page, expected_shortcodes: Sequence[str]):
    return _accept(run, page, expected_shortcodes)
