"""Small synchronous integration API for the Apify Instagram Transcript Actor.

Copy this file and reliable_actor.py together, or import as
``examples.python.client`` from the repository root. Importing this module does not read
credentials, load dotenv, create files, or access the network.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlparse

if __package__:  # Package import (for example, ``examples.python.client``).
    from .reliable_actor import (
        APPROVED_BUILD_NUMBER,
        STATUSES,
        ApiError,
        RestTransport,
        build_run_input,
        execute_input,
        safe_error,
        validate_build,
        validate_run_charge_cap,
    )
else:  # Copy both modules beside one another and import ``client``.
    from reliable_actor import (
        APPROVED_BUILD_NUMBER,
        STATUSES,
        ApiError,
        RestTransport,
        build_run_input,
        execute_input,
        safe_error,
        validate_build,
        validate_run_charge_cap,
    )

DEFAULT_ACTOR_ID = "apple_yang/instagram-transcripts-scraper"
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_DATASET_LIMIT = 100
_REEL_URL = re.compile(r"^https://(?:www\.)?instagram\.com/(?:reel|reels|p)/[A-Za-z0-9_-]+/?$")
_BUSINESS_STATUSES = {"success", "actor_error", "empty", "no_transcript", "unknown", "run_failed"}
_USERNAME = re.compile(r"^[A-Za-z0-9._]+$")
_PROFILE_DATE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")
_PROFILE_RELATIVE = re.compile(r"^\d+\s*(?:day|week|month|year)s?$")


@dataclass(frozen=True)
class TranscriptResult:
    """Outcome of one Actor Run; ``items`` retains the Actor's original item fields."""

    status: str
    text: str | None
    segments: list[Any]
    items: list[dict[str, Any]]
    run_id: str | None
    dataset_id: str | None
    source_url: str
    error: str | None
    dataset_complete: bool | None

    @property
    def succeeded(self) -> bool:
        return self.status == "success"


@dataclass(frozen=True)
class BulkItemResult:
    """Attribution of one input URL to zero, one, or multiple Dataset items."""

    url: str
    status: str
    text: str | None
    segments: list[Any]
    items: list[dict[str, Any]]
    error: str | None

    @property
    def item(self) -> dict[str, Any] | None:
        return self.items[0] if len(self.items) == 1 else None


@dataclass(frozen=True)
class BulkResult:
    """One Native Bulk Run and its per-input results."""

    status: str
    results: list[BulkItemResult]
    extra_results: list[dict[str, Any]]
    run_id: str | None
    dataset_id: str | None
    dataset_complete: bool
    counts: dict[str, int]
    raw_items: list[dict[str, Any]]
    error: str | None = None


@dataclass(frozen=True)
class ProfilePost:
    """A Profile Dataset record with convenient fields and the untouched Actor item."""

    url: str | None
    type: str | None
    owner_username: str | None
    caption: str | None
    timestamp: Any
    video_url: str | None
    video_duration: int | float | None
    status: str
    raw: dict[str, Any] | Any
    error: str | None = None


@dataclass(frozen=True)
class ProfileResult:
    """Result of one Profile Run; Profile success does not require transcript fields."""

    status: str
    posts: list[ProfilePost]
    usernames: list[str]
    run_id: str | None
    dataset_id: str | None
    dataset_complete: bool
    error: str | None
    raw_items: list[dict[str, Any] | Any]


class TranscriptClientError(Exception):
    """Base class for errors callers should handle explicitly."""


class ConfigurationError(TranscriptClientError, ValueError):
    """Invalid URL, credentials, timeout, Actor ID, Build, or charge-cap configuration."""


class ProtocolError(TranscriptClientError):
    """The runner returned a malformed or contradictory result."""

    def __init__(self, message: str, *, run_id: str | None = None, dataset_id: str | None = None):
        super().__init__(message)
        self.run_id = run_id
        self.dataset_id = dataset_id


class CreationUnknownError(TranscriptClientError):
    """POST may have created a Run; do not call again blindly."""


class TranscriptTransportError(TranscriptClientError):
    """A definite transport or post-creation retrieval failure."""

    def __init__(self, message: str, *, run_id: str | None = None, dataset_id: str | None = None):
        super().__init__(message)
        self.run_id = run_id
        self.dataset_id = dataset_id


class _MemoryJournal:
    """Journal-shaped in-memory sink; the reusable API creates no local files by default."""

    def __init__(self):
        self.records: list[dict[str, Any]] = []

    def append(self, record: dict[str, Any]) -> None:
        self.records.append(record.copy())


def _validate_url(url: str) -> str:
    if not isinstance(url, str) or not url or url != url.strip() or not _REEL_URL.fullmatch(url):
        raise ConfigurationError("url must be a bare HTTPS Instagram Reel URL, not a Markdown link")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"instagram.com", "www.instagram.com"} or parsed.query or parsed.fragment:
        raise ConfigurationError("url must not contain query parameters or a fragment")
    return url


def _positive_timeout(value: float | None) -> float:
    if value is None:
        return float(DEFAULT_TIMEOUT_SECONDS)
    if isinstance(value, bool):
        raise ConfigurationError("timeout must be a finite positive number of seconds")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ConfigurationError("timeout must be a finite positive number of seconds") from None
    if not math.isfinite(result) or result <= 0:
        raise ConfigurationError("timeout must be a finite positive number of seconds")
    return result


def _bulk_identity(url: str) -> tuple[str, str]:
    """Return conservative host-normalized URL key and exact path shortcode."""
    parsed = urlparse(url)
    return "https://instagram.com" + parsed.path, parsed.path.rstrip("/").rsplit("/", 1)[-1]


def validate_bulk_input(
    urls: Any,
    *,
    results_limit: int | None = None,
    skip_pinned_posts: bool | None = None,
    include_shares_count: bool | None = None,
) -> dict[str, Any]:
    """Validate Native Bulk arguments before any transport call and build Actor camelCase input."""
    if isinstance(urls, (str, bytes)) or not isinstance(urls, (list, tuple)) or not urls:
        raise ConfigurationError("urls must be a non-empty list or tuple of Instagram Reel URLs")
    url_keys: set[str] = set()
    shortcodes: set[str] = set()
    clean_urls: list[str] = []
    for index, url in enumerate(urls):
        try:
            clean = _validate_url(url)
        except ConfigurationError as exc:
            raise ConfigurationError(f"urls[{index}]: {exc}") from None
        key, shortcode = _bulk_identity(clean)
        if key in url_keys or shortcode in shortcodes:
            raise ConfigurationError(f"urls[{index}] duplicates or ambiguously aliases another Reel input")
        url_keys.add(key)
        shortcodes.add(shortcode)
        clean_urls.append(clean)

    if results_limit is not None and (isinstance(results_limit, bool) or not isinstance(results_limit, int) or results_limit < 1):
        raise ConfigurationError("results_limit must be a positive integer")
    if skip_pinned_posts is not None and not isinstance(skip_pinned_posts, bool):
        raise ConfigurationError("skip_pinned_posts must be a boolean")
    if include_shares_count is not None and not isinstance(include_shares_count, bool):
        raise ConfigurationError("include_shares_count must be a boolean")

    actor_input: dict[str, Any] = {"bulkUrls": clean_urls}
    if results_limit is not None:
        actor_input["resultsLimit"] = results_limit
    if skip_pinned_posts is not None:
        actor_input["skipPinnedPosts"] = skip_pinned_posts
    if include_shares_count is not None:
        actor_input["includeSharesCount"] = include_shares_count
    return actor_input


def attribute_bulk_items(
    urls: list[str],
    raw_items: list[dict[str, Any]],
    *,
    dataset_complete: bool,
) -> tuple[list[BulkItemResult], list[dict[str, Any]], dict[str, int], str]:
    """Attribute items by exact URL key, or exact shortcode only when URL is absent."""
    input_keys: dict[str, int] = {}
    shortcode_indices: dict[str, list[int]] = {}
    for index, url in enumerate(urls):
        key, shortcode = _bulk_identity(url)
        input_keys[key] = index
        shortcode_indices.setdefault(shortcode, []).append(index)

    mapped: list[list[dict[str, Any]]] = [[] for _ in urls]
    extra_results: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            extra_results.append({"status": "unknown", "reason": "dataset_item_not_object", "item": item})
            continue

        item_url = item.get("url")
        code = item.get("code")
        shortcode_matches = shortcode_indices.get(code, []) if isinstance(code, str) else []
        target_index = None
        reason = None
        if item_url is not None:
            try:
                valid_url = _validate_url(item_url)
                url_key, url_shortcode = _bulk_identity(valid_url)
            except ConfigurationError:
                reason = "invalid_output_url"
            else:
                candidate = input_keys.get(url_key)
                if candidate is None:
                    reason = "output_url_not_in_input"
                elif isinstance(code, str) and code != url_shortcode:
                    reason = "url_code_conflict"
                elif shortcode_matches and shortcode_matches != [candidate]:
                    reason = "ambiguous_url_code_mapping"
                else:
                    target_index = candidate
        elif isinstance(code, str):
            if len(shortcode_matches) == 1:
                target_index = shortcode_matches[0]
            else:
                reason = "missing_or_ambiguous_shortcode"
        else:
            reason = "missing_mapping_identity"

        if target_index is None:
            extra_results.append({"status": "unknown", "reason": reason or "unmapped_output", "item": item})
        else:
            mapped[target_index].append(item)

    rows: list[BulkItemResult] = []
    counts = {name: 0 for name in ("success_transcript", "actor_error", "no_transcript", "missing_result", "duplicate_result", "unknown")}
    for index, (url, associated) in enumerate(zip(urls, mapped)):
        if not associated:
            status = "unknown" if not dataset_complete else "missing_result"
            error = "Dataset is incomplete; absence of a result is unknown" if not dataset_complete else "No Dataset item maps to this input URL"
            rows.append(BulkItemResult(url, status, None, [], [], error))
        elif len(associated) > 1:
            rows.append(BulkItemResult(url, "duplicate_result", None, [], associated, "Multiple Dataset items map to this input URL"))
        else:
            item = associated[0]
            item_error = item.get("errMsg")
            if item_error is not None and str(item_error).strip():
                status, error = "actor_error", safe_error(item_error)
            elif isinstance(item.get("text"), str) and item["text"].strip():
                status, error = "success_transcript", None
            elif item.get("text") is None or isinstance(item.get("text"), str):
                status, error = "no_transcript", "Mapped Dataset item has no non-empty transcript"
            else:
                status, error = "unknown", "Mapped Dataset item has an unsupported transcript type"
            segments = item.get("segments") if isinstance(item.get("segments"), list) else []
            rows.append(BulkItemResult(url, status, item.get("text") if isinstance(item.get("text"), str) else None, segments, [item], error))
        counts[rows[-1].status] += 1

    uncertain = not dataset_complete or bool(extra_results) or any(row.status in {"missing_result", "duplicate_result", "unknown"} for row in rows)
    successes = counts["success_transcript"]
    definite_failures = counts["actor_error"] + counts["no_transcript"]
    if uncertain:
        overall = "unknown"
    elif successes == len(urls):
        overall = "all_success"
    elif successes:
        overall = "partial_success"
    elif definite_failures == len(urls):
        overall = "all_failed"
    else:
        overall = "unknown"
    return rows, extra_results, counts, overall


def get_transcript(
    url: str,
    *,
    token: str | None = None,
    actor_id: str | None = None,
    build: str | None = None,
    timeout: float | None = None,
    max_total_charge_usd: str | float | None = None,
    require_charge_cap: bool | None = None,
    dataset_limit: int = DEFAULT_DATASET_LIMIT,
    transport: Any = None,
    journal: Any = None,
) -> TranscriptResult:
    """Run one Reel through the approved Actor Build and return transcript plus raw items.

    ``token`` overrides ``APIFY_TOKEN``. If omitted, the environment is checked only when this
    function is called. ``transport`` and ``journal`` are injection seams for offline tests and
    advanced callers; by default the API uses the shared REST runner and an in-memory journal.
    """
    source_url = _validate_url(url)
    selected_token = token if token is not None else os.getenv("APIFY_TOKEN")
    if not isinstance(selected_token, str) or not selected_token.strip():
        raise ConfigurationError("APIFY_TOKEN is required; pass token=... or set it in the process environment")

    selected_actor = actor_id if actor_id is not None else os.getenv("APIFY_ACTOR_ID", DEFAULT_ACTOR_ID)
    if not isinstance(selected_actor, str) or not selected_actor.strip() or selected_actor.strip().startswith("/"):
        raise ConfigurationError("actor_id must be a non-empty Apify Actor ID or owner/name")
    selected_actor = selected_actor.strip()

    selected_build = APPROVED_BUILD_NUMBER if build is None else build
    try:
        selected_build = validate_build(selected_build, required=True)
        cap = max_total_charge_usd if max_total_charge_usd is not None else os.getenv("APIFY_MAX_TOTAL_CHARGE_USD")
        require_cap = require_charge_cap if require_charge_cap is not None else os.getenv("APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD") == "1"
        validate_run_charge_cap(cap, required=require_cap)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from None

    run_timeout = _positive_timeout(timeout)
    if isinstance(dataset_limit, bool) or not isinstance(dataset_limit, int) or dataset_limit <= 0:
        raise ConfigurationError("dataset_limit must be a positive integer")

    active_transport = transport if transport is not None else RestTransport(selected_token)
    active_journal = journal if journal is not None else _MemoryJournal()
    try:
        outcome = execute_input(
            transport=active_transport,
            actor_id=selected_actor,
            run_input=build_run_input(source_url),
            source_url=source_url,
            journal=active_journal,
            deadline_seconds=run_timeout,
            max_total_charge_usd=cap,
            require_charge_cap=bool(require_cap),
            build=selected_build,
            require_build=True,
            dataset_limit=dataset_limit,
        )
    except ApiError as exc:
        raise TranscriptTransportError(str(exc)) from None

    if not isinstance(outcome, dict) or not isinstance(outcome.get("status"), str):
        raise ProtocolError("Runner returned a malformed result")
    status = outcome["status"]
    run_id = outcome.get("runId")
    dataset_id = outcome.get("datasetId")
    if status == "creation_unknown":
        raise CreationUnknownError(
            f"Run creation outcome is unknown (Run ID unavailable): {outcome.get('error') or 'reconcile before retrying'}; do not call get_transcript again blindly"
        )
    if status == "transport_error":
        if outcome.get("stage") == "build_mismatch":
            raise ProtocolError(
                f"Run was created but its Build could not be verified: {outcome.get('error') or 'Build mismatch'}; do not create a replacement Run automatically",
                run_id=run_id,
                dataset_id=dataset_id,
            )
        detail = outcome.get("error") or "Apify transport failed"
        if run_id:
            detail = f"{detail}; Run {run_id} already exists. Reconcile or resume that Run; do not call get_transcript again to replace it"
        raise TranscriptTransportError(
            detail,
            run_id=run_id,
            dataset_id=dataset_id,
        )
    if status not in _BUSINESS_STATUSES or status not in STATUSES:
        raise ProtocolError(f"Runner returned unsupported status: {status!r}", run_id=run_id, dataset_id=dataset_id)

    raw_items = outcome.get("rawItems", [])
    if not isinstance(raw_items, list) or any(not isinstance(item, dict) for item in raw_items):
        raise ProtocolError("Runner returned malformed Dataset items", run_id=run_id, dataset_id=dataset_id)
    items = raw_items  # Keep all original Actor item fields, including metadata unknown to this client.
    transcript_item = next((item for item in items if isinstance(item.get("text"), str) and item["text"].strip()), None)
    text = transcript_item.get("text") if transcript_item else None
    segments_value = transcript_item.get("segments") if transcript_item else None
    segments = segments_value if isinstance(segments_value, list) else []
    if status == "success" and text is None:
        raise ProtocolError("Runner reported success without a non-empty transcript", run_id=run_id, dataset_id=dataset_id)

    return TranscriptResult(
        status=status,
        text=text,
        segments=segments,
        items=items,
        run_id=run_id,
        dataset_id=dataset_id,
        source_url=outcome.get("sourceUrl", source_url),
        error=outcome.get("error") or None,
        dataset_complete=outcome.get("datasetComplete"),
    )


def get_transcripts(
    urls: list[str] | tuple[str, ...],
    *,
    token: str | None = None,
    actor_id: str | None = None,
    build: str | None = None,
    timeout: float | None = None,
    max_total_charge_usd: str | float | None = None,
    require_charge_cap: bool | None = None,
    dataset_limit: int = DEFAULT_DATASET_LIMIT,
    results_limit: int | None = None,
    skip_pinned_posts: bool | None = None,
    include_shares_count: bool | None = None,
    transport: Any = None,
    journal: Any = None,
) -> BulkResult:
    """Submit all supplied URLs in exactly one Native Bulk Actor Run.

    The reusable API keeps no disk journal unless one is explicitly passed. URL mapping is
    conservative: exact URL path after normalizing only the Instagram ``www`` host, or an
    exact shortcode when the Dataset item has no URL.
    """
    actor_input = validate_bulk_input(
        urls,
        results_limit=results_limit,
        skip_pinned_posts=skip_pinned_posts,
        include_shares_count=include_shares_count,
    )
    selected_token = token if token is not None else os.getenv("APIFY_TOKEN")
    if not isinstance(selected_token, str) or not selected_token.strip():
        raise ConfigurationError("APIFY_TOKEN is required; pass token=... or set it in the process environment")
    selected_actor = actor_id if actor_id is not None else os.getenv("APIFY_ACTOR_ID", DEFAULT_ACTOR_ID)
    if not isinstance(selected_actor, str) or not selected_actor.strip() or selected_actor.strip().startswith("/"):
        raise ConfigurationError("actor_id must be a non-empty Apify Actor ID or owner/name")
    selected_actor = selected_actor.strip()

    selected_build = APPROVED_BUILD_NUMBER if build is None else build
    try:
        selected_build = validate_build(selected_build, required=True)
        cap = max_total_charge_usd if max_total_charge_usd is not None else os.getenv("APIFY_MAX_TOTAL_CHARGE_USD")
        require_cap = require_charge_cap if require_charge_cap is not None else os.getenv("APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD") == "1"
        validate_run_charge_cap(cap, required=require_cap)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from None

    run_timeout = _positive_timeout(timeout)
    if isinstance(dataset_limit, bool) or not isinstance(dataset_limit, int) or dataset_limit <= 0:
        raise ConfigurationError("dataset_limit must be a positive integer")
    active_transport = transport if transport is not None else RestTransport(selected_token)
    active_journal = journal if journal is not None else _MemoryJournal()
    source_label = "native_bulk:" + ",".join(actor_input["bulkUrls"])
    try:
        outcome = execute_input(
            transport=active_transport,
            actor_id=selected_actor,
            run_input=actor_input,
            source_url=source_label,
            journal=active_journal,
            deadline_seconds=run_timeout,
            max_total_charge_usd=cap,
            require_charge_cap=bool(require_cap),
            build=selected_build,
            require_build=True,
            dataset_limit=dataset_limit,
        )
    except ApiError as exc:
        raise TranscriptTransportError(str(exc)) from None

    if not isinstance(outcome, dict) or not isinstance(outcome.get("status"), str):
        raise ProtocolError("Runner returned a malformed result")
    run_id, dataset_id = outcome.get("runId"), outcome.get("datasetId")
    status = outcome["status"]
    if status == "creation_unknown":
        raise CreationUnknownError(
            f"Run creation outcome is unknown (Run ID unavailable): {outcome.get('error') or 'reconcile before retrying'}; do not call get_transcripts again blindly"
        )
    if status == "transport_error":
        detail = outcome.get("error") or "Apify transport failed"
        if run_id:
            detail = f"{detail}; Run {run_id} already exists. Reconcile that Run; do not call get_transcripts again to replace it"
        error_type = ProtocolError if outcome.get("stage") == "build_mismatch" else TranscriptTransportError
        raise error_type(detail, run_id=run_id, dataset_id=dataset_id)
    if status == "run_failed":
        raw_items: list[dict[str, Any]] = []
        complete = False
    else:
        raw_items = outcome.get("rawItems")
        complete = outcome.get("datasetComplete") is True
        if not isinstance(raw_items, list) or any(not isinstance(item, dict) for item in raw_items):
            raise ProtocolError("Runner returned malformed Dataset items", run_id=run_id, dataset_id=dataset_id)

    rows, extras, counts, overall = attribute_bulk_items(actor_input["bulkUrls"], raw_items, dataset_complete=complete)
    if status == "run_failed":
        # There is no per-input Dataset evidence for a failed Actor Run.
        rows = [BulkItemResult(url, "unknown", None, [], [], outcome.get("error") or "Run failed before item-level results were available") for url in actor_input["bulkUrls"]]
        counts = {name: 0 for name in ("success_transcript", "actor_error", "no_transcript", "missing_result", "duplicate_result", "unknown")}
        counts["unknown"] = len(rows)
        overall = "unknown"
    return BulkResult(
        status=overall,
        results=rows,
        extra_results=extras,
        run_id=run_id,
        dataset_id=dataset_id,
        dataset_complete=complete,
        counts=counts,
        raw_items=raw_items,
        error=outcome.get("error") or None,
    )


def _validate_profile_usernames(usernames: Any) -> list[str]:
    if isinstance(usernames, str):
        values = [usernames]
    elif isinstance(usernames, (list, tuple)):
        values = list(usernames)
    else:
        raise ConfigurationError("usernames must be a username or a non-empty list/tuple of usernames")
    if not values:
        raise ConfigurationError("at least one explicit username is required")
    seen: set[str] = set()
    for index, username in enumerate(values):
        if (not isinstance(username, str) or not username or username != username.strip()
                or not _USERNAME.fullmatch(username) or not any(char.isalnum() for char in username)
                or username.startswith(".") or username.endswith(".") or ".." in username):
            raise ConfigurationError(f"usernames[{index}] must be an Instagram-style name without @, whitespace, or invalid dot placement")
        identity = username.casefold()
        if identity in seen:
            raise ConfigurationError(f"usernames[{index}] duplicates or ambiguously aliases another username")
        seen.add(identity)
    return values


def _validate_profile_date(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise ConfigurationError("only_posts_newer_than must be a non-empty supported date or relative period")
    if _PROFILE_DATE.fullmatch(value):
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ConfigurationError("only_posts_newer_than must be a real YYYY-MM-DD calendar date") from None
        return value
    if _PROFILE_RELATIVE.fullmatch(value) and int(re.match(r"\d+", value).group()) > 0:
        return value
    raise ConfigurationError("only_posts_newer_than accepts YYYY-MM-DD or a relative day/week/month/year value; ISO timestamps remain unverified")


def build_profile_input(
    usernames: Any,
    *,
    results_limit: int | None = None,
    only_posts_newer_than: str | None = None,
    skip_pinned_posts: bool | None = None,
    include_shares_count: bool | None = None,
) -> dict[str, Any]:
    """Validate the Profile mode allowlist and build the Actor's camelCase input."""
    selected_usernames = _validate_profile_usernames(usernames)
    if results_limit is not None and (isinstance(results_limit, bool) or not isinstance(results_limit, int) or results_limit <= 0):
        raise ConfigurationError("results_limit must be a positive integer")
    selected_date = _validate_profile_date(only_posts_newer_than)
    if skip_pinned_posts is not None and not isinstance(skip_pinned_posts, bool):
        raise ConfigurationError("skip_pinned_posts must be a boolean")
    if include_shares_count is not None and not isinstance(include_shares_count, bool):
        raise ConfigurationError("include_shares_count must be a boolean")

    actor_input: dict[str, Any] = {"usernames": selected_usernames}
    if results_limit is not None:
        actor_input["resultsLimit"] = results_limit
    if selected_date is not None:
        actor_input["onlyPostsNewerThan"] = selected_date
    if skip_pinned_posts is not None:
        actor_input["skipPinnedPosts"] = skip_pinned_posts
    if include_shares_count is not None:
        actor_input["includeSharesCount"] = include_shares_count
    return actor_input


def _profile_post(item: Any, requested_usernames: list[str]) -> tuple[ProfilePost, bool]:
    if not isinstance(item, dict):
        post = ProfilePost(None, None, None, None, None, None, None, "unknown", item, "Dataset item is not an object")
        return post, False

    error_value = item.get("errMsg")
    if error_value is not None and str(error_value).strip():
        post = ProfilePost(
            item.get("url") if isinstance(item.get("url"), str) else None,
            item.get("type") if isinstance(item.get("type"), str) else None,
            item.get("ownerUsername") if isinstance(item.get("ownerUsername"), str) else None,
            item.get("caption") if isinstance(item.get("caption"), str) else None,
            item.get("timestamp"),
            item.get("videoUrl") if isinstance(item.get("videoUrl"), str) else None,
            item.get("videoDuration") if isinstance(item.get("videoDuration"), (int, float)) and not isinstance(item.get("videoDuration"), bool) else None,
            "actor_error", item, safe_error(error_value),
        )
        return post, True

    url = item.get("url")
    valid_url = isinstance(url, str) and bool(re.fullmatch(
        r"https://(?:www\.)?instagram\.com/(?:p|reel|reels)/[A-Za-z0-9_-]+/?", url
    ))
    post_type = item.get("type") if isinstance(item.get("type"), str) and item["type"].strip() else None
    owner_username = item.get("ownerUsername") if isinstance(item.get("ownerUsername"), str) and item["ownerUsername"].strip() else None
    has_metadata = bool(
        post_type or owner_username
        or (isinstance(item.get("caption"), str) and item["caption"].strip())
        or any(isinstance(item.get(key), str) and item[key].strip() for key in ("id", "pk", "img"))
        or ("timestamp" in item and item.get("timestamp") is not None and item.get("timestamp") != "")
    )
    recognizable = valid_url and bool(post_type or has_metadata)
    ownership_known = True
    if len(requested_usernames) > 1:
        ownership_known = owner_username in requested_usernames
    elif owner_username is not None and owner_username != requested_usernames[0]:
        ownership_known = False

    status = "success" if recognizable and ownership_known else "unknown"
    reason = None if status == "success" else (
        "Post owner is missing or does not match a requested account" if recognizable else
        "Dataset item lacks recognizable Profile post metadata"
    )
    video_duration = item.get("videoDuration")
    if isinstance(video_duration, bool) or not isinstance(video_duration, (int, float)):
        video_duration = None
    post = ProfilePost(
        url if valid_url else None,
        post_type,
        owner_username,
        item.get("caption") if isinstance(item.get("caption"), str) else None,
        item.get("timestamp"),
        item.get("videoUrl") if isinstance(item.get("videoUrl"), str) else None,
        video_duration,
        status,
        item,
        reason,
    )
    return post, recognizable and ownership_known


def get_profile_posts(
    usernames: str | list[str] | tuple[str, ...],
    *,
    token: str | None = None,
    actor_id: str | None = None,
    build: str | None = None,
    timeout: float | None = None,
    max_total_charge_usd: str | float | None = None,
    require_charge_cap: bool | None = None,
    dataset_limit: int = DEFAULT_DATASET_LIMIT,
    results_limit: int | None = None,
    only_posts_newer_than: str | None = None,
    skip_pinned_posts: bool | None = None,
    include_shares_count: bool | None = None,
    transport: Any = None,
    journal: Any = None,
) -> ProfileResult:
    """Collect Profile post metadata in one native ``usernames`` Actor Run.

    Profile success is based on recognizable post metadata, never on transcript fields. For
    multi-account input, each item must name a requested ``ownerUsername`` to be attributed.
    """
    actor_input = build_profile_input(
        usernames,
        results_limit=results_limit,
        only_posts_newer_than=only_posts_newer_than,
        skip_pinned_posts=skip_pinned_posts,
        include_shares_count=include_shares_count,
    )
    selected_usernames = actor_input["usernames"]
    selected_token = token if token is not None else os.getenv("APIFY_TOKEN")
    if not isinstance(selected_token, str) or not selected_token.strip():
        raise ConfigurationError("APIFY_TOKEN is required; pass token=... or set it in the process environment")
    selected_actor = actor_id if actor_id is not None else os.getenv("APIFY_ACTOR_ID", DEFAULT_ACTOR_ID)
    if not isinstance(selected_actor, str) or not selected_actor.strip() or selected_actor.strip().startswith("/"):
        raise ConfigurationError("actor_id must be a non-empty Apify Actor ID or owner/name")
    selected_actor = selected_actor.strip()

    selected_build = APPROVED_BUILD_NUMBER if build is None else build
    try:
        selected_build = validate_build(selected_build, required=True)
        cap = max_total_charge_usd if max_total_charge_usd is not None else os.getenv("APIFY_MAX_TOTAL_CHARGE_USD")
        require_cap = require_charge_cap if require_charge_cap is not None else os.getenv("APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD") == "1"
        validate_run_charge_cap(cap, required=require_cap)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from None

    run_timeout = _positive_timeout(timeout)
    if isinstance(dataset_limit, bool) or not isinstance(dataset_limit, int) or dataset_limit <= 0:
        raise ConfigurationError("dataset_limit must be a positive integer")
    active_transport = transport if transport is not None else RestTransport(selected_token)
    active_journal = journal if journal is not None else _MemoryJournal()
    source_label = "profile:" + ",".join(selected_usernames)
    try:
        outcome = execute_input(
            transport=active_transport,
            actor_id=selected_actor,
            run_input=actor_input,
            source_url=source_label,
            journal=active_journal,
            deadline_seconds=run_timeout,
            max_total_charge_usd=cap,
            require_charge_cap=bool(require_cap),
            build=selected_build,
            require_build=True,
            dataset_limit=dataset_limit,
        )
    except ApiError as exc:
        raise TranscriptTransportError(str(exc)) from None

    if not isinstance(outcome, dict) or not isinstance(outcome.get("status"), str):
        raise ProtocolError("Runner returned a malformed result")
    run_id, dataset_id = outcome.get("runId"), outcome.get("datasetId")
    run_status = outcome["status"]
    if run_status == "creation_unknown":
        raise CreationUnknownError(
            f"Run creation outcome is unknown (Run ID unavailable): {outcome.get('error') or 'reconcile before retrying'}; do not call get_profile_posts again blindly"
        )
    if run_status == "transport_error":
        detail = outcome.get("error") or "Apify transport failed"
        if run_id:
            detail = f"{detail}; Run {run_id} already exists. Reconcile that Run; do not call get_profile_posts again to replace it"
        error_type = ProtocolError if outcome.get("stage") == "build_mismatch" else TranscriptTransportError
        raise error_type(detail, run_id=run_id, dataset_id=dataset_id)

    if run_status == "run_failed":
        return ProfileResult("run_failed", [], selected_usernames, run_id, dataset_id, False,
                             outcome.get("error") or "Actor Run failed", [])
    raw_items = outcome.get("rawItems")
    if not isinstance(raw_items, list):
        raise ProtocolError("Runner returned malformed Dataset items", run_id=run_id, dataset_id=dataset_id)
    dataset_complete = outcome.get("datasetComplete") is True
    posts: list[ProfilePost] = []
    metadata_ok = True
    for item in raw_items:
        post, recognized = _profile_post(item, selected_usernames)
        posts.append(post)
        if post.status != "actor_error" and not recognized:
            metadata_ok = False

    has_actor_error = any(post.status == "actor_error" for post in posts)
    if has_actor_error:
        result_status = "actor_error"
    elif not dataset_complete:
        result_status = "unknown"
    elif not raw_items:
        result_status = "empty"
    elif metadata_ok:
        result_status = "success"
    else:
        result_status = "unknown"
    error = None
    if result_status == "actor_error":
        error = "One or more Profile items contain a non-empty errMsg"
    elif result_status == "unknown":
        error = "Profile Dataset is incomplete or contains unrecognized/unattributed items"
    return ProfileResult(result_status, posts, selected_usernames, run_id, dataset_id,
                         dataset_complete, error, raw_items)
