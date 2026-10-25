"""Shared, offline-safe parsing for Apify MCP run and dataset results.

The native response paths in this module describe an observation recorded on
2026-10-25, not a promise made by the MCP protocol.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

OBSERVED_DATASET_PATH = "storages.datasets.default.id"
DATASET_ID_ALIASES = ("defaultDatasetId", "defaultDatasetID", "datasetId", "dataset_id")
PAGE_URL_KEYS = ("url",)
CODE_KEYS = ("code", "shortCode", "shortcode")
MEDIA_KEYS = frozenset(("videoUrl", "audioUrl", "img", "avatarUri"))
ERROR_KEYS = ("errMsg", "error", "errorMessage")
TERMINAL_STATUSES = frozenset(("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"))
EXPECTED_BUILD_NUMBER = "0.0.50"
EXPECTED_BUILD_ID = "aJLRmMdQapLQRT4sJ"


class MCPParseError(ValueError):
    """A fail-closed parsing or binding error with a stable machine code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RunMetadata:
    run_id: str | None
    actor_id: str | None
    actor_name: str | None
    status: str | None
    dataset_id: str | None
    dataset_id_path: str
    dataset_item_count: int | None
    dataset_fields: tuple[str, ...]
    build_id: str | None
    build_number: str | None
    build_verified: str
    run_source: str
    cost_value: float | int | None
    cost_path: str | None
    raw_fields_present: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetPage:
    dataset_id: str | None
    items: tuple[dict[str, Any], ...]
    item_count: int | None
    total_item_count: int | None
    offset: int | None
    limit: int | None
    items_source: str
    complete: bool | None
    raw_fields_present: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["items"] = list(self.items)
        return result


@dataclass(frozen=True)
class ReelResult:
    shortcode: str
    match: str
    transcript_present: bool | None
    segments_count: int | None
    identity: str | None
    business_error: str | None
    matched_count: int
    item_keys: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["item_keys"] = list(self.item_keys)
        return result


@dataclass(frozen=True)
class ProfileInput:
    """Validated Profile call context; this is not an Actor-schema guarantee."""

    usernames: tuple[str, ...]
    normalized_usernames: tuple[str, ...]
    results_limit: int | None
    skip_pinned_posts: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "usernames": list(self.usernames),
            "normalizedUsernames": list(self.normalized_usernames),
            "resultsLimit": self.results_limit,
            "skipPinnedPosts": self.skip_pinned_posts,
        }


@dataclass(frozen=True)
class ProfileItemResult:
    """Profile item summary that deliberately excludes caption/transcript bodies."""

    status: str
    requested_owner: str | None
    owner_username: str | None
    owner_field_state: str
    attribution: str
    author_field_conflict: bool
    post_identity: str
    post_keys: tuple[str, ...]
    duplicate_status: str
    text_state: str
    segments_state: str
    segments_count: int | None
    err_msg_state: str
    err_msg_state_detail: str
    err_msg_whitespace_only: bool
    business_error: str | None
    business_error_sources: tuple[str, ...]
    business_error_messages: tuple[str, ...]
    business_error_field_states: tuple[tuple[str, str], ...]
    business_error_conflict: bool
    transcript_assessment: str
    transcript_data_state: str
    item_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["post_keys"] = list(self.post_keys)
        result["item_keys"] = list(self.item_keys)
        result["business_error_sources"] = list(self.business_error_sources)
        result["business_error_messages"] = list(self.business_error_messages)
        result["business_error_field_states"] = [list(entry) for entry in self.business_error_field_states]
        return result


@dataclass(frozen=True)
class ProfilePageLedger:
    dataset_id: str
    items: tuple[dict[str, Any], ...]
    page_count: int
    completeness: str
    total_item_count: int | None
    parsed_item_count: int
    offsets: tuple[int | None, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "page_count": self.page_count,
            "completeness": self.completeness,
            "total_item_count": self.total_item_count,
            "parsed_item_count": self.parsed_item_count,
            "offsets": list(self.offsets),
        }


def _build_verification(build_number: str | None, build_id: str | None,
                        expected_build_number: str | None,
                        expected_build_id: str | None) -> str:
    """Compare every supplied pin before deciding which metadata is incomplete."""
    has_number = isinstance(build_number, str) and bool(build_number)
    has_id = isinstance(build_id, str) and bool(build_id)
    expects_number = isinstance(expected_build_number, str) and bool(expected_build_number)
    expects_id = isinstance(expected_build_id, str) and bool(expected_build_id)
    if not has_number and not has_id:
        return "UNVERIFIED_SOURCE_ABSENT"
    if ((expects_number and has_number and build_number != expected_build_number)
            or (expects_id and has_id and build_id != expected_build_id)):
        return "BUILD_DRIFT"
    if not expects_number and not expects_id:
        return "UNVERIFIED_EXPECTATION_ABSENT"
    if has_number and has_id and expects_number and expects_id:
        return "VERIFIED"
    return "UNVERIFIED_INCOMPLETE_METADATA"


def _json_objects_from_content(payload: Mapping[str, Any]) -> list[Any]:
    decoded: list[Any] = []
    content = payload.get("content")
    if not isinstance(content, list):
        return decoded
    for block in content:
        if not isinstance(block, Mapping) or not isinstance(block.get("text"), str):
            continue
        try:
            decoded.append(json.loads(block["text"]))
        except (json.JSONDecodeError, TypeError):
            continue
    return decoded


def iter_nodes(payload: Any, *, max_depth: int = 32) -> Iterable[tuple[tuple[str, ...], Any]]:
    """Walk mappings/lists plus JSON objects in MCP text blocks, without cycles."""
    seen: set[int] = set()
    stack: list[tuple[tuple[str, ...], Any, int]] = [((), payload, 0)]
    while stack:
        path, node, depth = stack.pop()
        yield path, node
        if depth >= max_depth or not isinstance(node, (Mapping, list)):
            continue
        ident = id(node)
        if ident in seen:
            continue
        seen.add(ident)
        if isinstance(node, Mapping):
            children = [(path + (str(key),), value, depth + 1) for key, value in node.items()]
            nested_json: list[Any] = []
            content = node.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, Mapping) or not isinstance(block.get("text"), str):
                        continue
                    try:
                        nested_json.append(json.loads(block["text"]))
                    except (json.JSONDecodeError, TypeError):
                        continue
            children.extend((path + ("content-json", str(i)), value, depth + 1)
                            for i, value in enumerate(nested_json))
            stack.extend(reversed(children))
        else:
            stack.extend((path + (str(i),), value, depth + 1)
                         for i, value in reversed(list(enumerate(node))))


def response_is_error(payload: Mapping[str, Any]) -> bool:
    """Only literal true signals an MCP tool error; absent is UNKNOWN/not true."""
    return payload.get("isError") is True


def _path_value(payload: Any, path: Sequence[str]) -> Any:
    current = payload
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _all_alias_ids(payload: Any) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[int] = set()
    stack: list[tuple[tuple[str, ...], Any, int]] = [((), payload, 0)]
    while stack:
        path, node, depth = stack.pop()
        if depth > 32:
            continue
        if isinstance(node, list):
            identity = id(node)
            if identity in seen:
                continue
            seen.add(identity)
            stack.extend((path + (str(index),), child, depth + 1)
                         for index, child in reversed(list(enumerate(node))))
            continue
        if not isinstance(node, Mapping):
            continue
        identity = id(node)
        if identity in seen:
            continue
        seen.add(identity)
        for key in DATASET_ID_ALIASES:
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                found.append((".".join(path + (key,)), value.strip()))
        children = []
        for key, value in node.items():
            if key in ("keyValueStores", "restFallback"):
                continue
            children.append((path + (str(key),), value, depth + 1))
        content = node.get("content")
        if isinstance(content, list):
            for index, block in enumerate(content):
                if not isinstance(block, Mapping) or not isinstance(block.get("text"), str):
                    continue
                try:
                    decoded = json.loads(block["text"])
                except (json.JSONDecodeError, TypeError):
                    continue
                children.append((path + ("content-json", str(index)), decoded, depth + 1))
        stack.extend(reversed(children))
    return found


def _first_string(payload: Any, keys: Sequence[str]) -> str | None:
    for _path, node in iter_nodes(payload):
        if isinstance(node, Mapping):
            for key in keys:
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def _first_present(payload: Any, key: str) -> tuple[bool, Any, str | None]:
    for path, node in iter_nodes(payload):
        if isinstance(node, Mapping) and key in node:
            return True, node[key], ".".join(path + (key,))
    return False, None, None


def find_values(payload: Any, wanted: Iterable[str], found: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compatibility helper for legacy report fields, using the shared walker."""
    names = set(wanted)
    if found is None:
        found = {}
    for _path, node in iter_nodes(payload):
        if isinstance(node, Mapping):
            for key in names:
                value = node.get(key)
                if value not in (None, ""):
                    found.setdefault(key, value)
    return found


def normalize_page_url(value: Any) -> str | None:
    return _shortcode(value)


def _run_identity_values(payload: Any, *, allow_contextual_id: bool = True) -> list[str]:
    values: list[str] = []
    for _path, node in iter_nodes(payload):
        if isinstance(node, Mapping):
            for key in ("runId", "run_id", "actorRunId"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    values.append(value.strip())
            # Legacy Run records may call the Run identifier `id`; accept it
            # only when the same object has Run metadata, never as a global id.
            if (allow_contextual_id and "id" in node
                    and any(key in node for key in ("status", "runStatus", "actorId", "actId"))):
                value = node.get("id")
                if isinstance(value, str) and value.strip():
                    values.append(value.strip())
    return values


def extract_run_identity(payload: Mapping[str, Any], *, expected_run_id: str | None = None,
                         allow_contextual_id: bool = False) -> str:
    """Return one explicit Run identity; never infer it from an arbitrary `id`."""
    values = set(_run_identity_values(payload, allow_contextual_id=allow_contextual_id))
    if not values:
        raise MCPParseError("RUN_IDENTITY_UNAVAILABLE", "Run ID is not present in the response")
    if len(values) > 1:
        raise MCPParseError("RUN_IDENTITY_CONFLICT", "Response contains conflicting Run IDs")
    run_id = next(iter(values))
    if expected_run_id is not None and run_id != expected_run_id:
        raise MCPParseError("RUN_IDENTITY_MISMATCH", "Run ID did not match the expected Run")
    return run_id


def _cost_field(payload: Any) -> tuple[float | int | None, str | None]:
    for path, node in iter_nodes(payload):
        if isinstance(node, Mapping) and isinstance(node.get("com.apify/ActorRun"), Mapping):
            scoped = node["com.apify/ActorRun"]
            if "usageTotalUsd" in scoped:
                value = scoped["usageTotalUsd"]
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return value, ".".join(path + ("com.apify/ActorRun", "usageTotalUsd"))
                return None, ".".join(path + ("com.apify/ActorRun", "usageTotalUsd"))
    # Compatibility for older response variants. Keep the actual source path;
    # never turn an absent usage field into a numeric zero.
    for path, node in iter_nodes(payload):
        if isinstance(node, Mapping) and "usageTotalUsd" in node:
            value = node["usageTotalUsd"]
            return (value if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
                    ".".join(path + ("usageTotalUsd",)))
    return None, None


def run_metadata(payload: Mapping[str, Any], *, expected_run_id: str | None = None,
                 allow_rest_fallback: bool = False, require_dataset_id: bool = True,
                 expected_build_number: str | None = None,
                 expected_build_id: str | None = None) -> RunMetadata:
    """Resolve run metadata path-first; optional REST data must be explicit.

    A caller-supplied fallback uses a mapping member named ``data`` and is
    labelled ``REST fallback``. This helper never performs network requests.
    """
    if response_is_error(payload):
        raise MCPParseError("MCP_TOOL_ERROR", "get-actor-run returned isError=true")
    run_id = extract_run_identity(payload, expected_run_id=expected_run_id, allow_contextual_id=True)

    path_candidates: list[tuple[str, str]] = []
    native_path = ("structuredContent", "storages", "datasets", "default", "id")
    direct_value = _path_value(payload, native_path)
    if isinstance(direct_value, str) and direct_value.strip():
        path_candidates.append((OBSERVED_DATASET_PATH, direct_value.strip()))
    for i, decoded in enumerate(_json_objects_from_content(payload)):
        content_value = _path_value(decoded, ("storages", "datasets", "default", "id"))
        if isinstance(content_value, str) and content_value.strip():
            path_candidates.append((f"content[{i}].text.{OBSERVED_DATASET_PATH}", content_value.strip()))
    if isinstance(payload.get("storages"), Mapping):
        root_value = _path_value(payload, ("storages", "datasets", "default", "id"))
        if isinstance(root_value, str) and root_value.strip():
            path_candidates.append((OBSERVED_DATASET_PATH, root_value.strip()))
    path_ids = {value for _, value in path_candidates}
    if len(path_ids) > 1:
        raise MCPParseError("DATASET_ID_CONFLICT", "Observed Dataset paths disagree")
    dataset_id = next(iter(path_ids), None)
    dataset_path = path_candidates[0][0] if path_candidates else ""

    aliases = _all_alias_ids(payload)
    rest_data = payload.get("restFallback") if allow_rest_fallback else None
    rest_id = rest_data.get("defaultDatasetId") if isinstance(rest_data, Mapping) else None
    if isinstance(rest_id, str) and rest_id.strip():
        rest_id = rest_id.strip()
        if dataset_id is not None and rest_id != dataset_id:
            raise MCPParseError("DATASET_ID_CONFLICT", "MCP and REST fallback Dataset IDs disagree")
        if any(value != rest_id for _, value in aliases):
            raise MCPParseError("DATASET_ID_CONFLICT", "REST fallback and Dataset aliases disagree")
    if dataset_id:
        conflicting = [(path, value) for path, value in aliases if value != dataset_id]
        if conflicting:
            raise MCPParseError("DATASET_ID_CONFLICT", "Path and alias Dataset IDs disagree")
    elif aliases:
        unique = {value for _, value in aliases}
        if len(unique) > 1:
            raise MCPParseError("DATASET_ID_CONFLICT", "Response contains conflicting Dataset IDs")
        dataset_id = next(iter(unique))
        dataset_path = aliases[0][0]

    source = "MCP"
    if dataset_id is None and rest_id is not None:
        dataset_id = rest_id
        dataset_path = "restFallback.defaultDatasetId"
        source = "MCP + REST diagnostic fallback"
    if dataset_id is None and require_dataset_id:
        raise MCPParseError("DATASET_ID_UNAVAILABLE", "No verified Dataset ID was present")

    structured = payload.get("structuredContent")
    structured = structured if isinstance(structured, Mapping) else None
    decoded_roots = _json_objects_from_content(payload)

    def preferred_string(keys: Sequence[str]) -> str | None:
        ordered = ([structured] if structured is not None else []) + [payload] + decoded_roots
        for source_node in ordered:
            if isinstance(source_node, Mapping):
                for key in keys:
                    value = source_node.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        return _first_string(payload, keys)

    status = preferred_string(("status", "runStatus"))
    if expected_run_id and (not status or status.upper() not in TERMINAL_STATUSES):
        raise MCPParseError("RUN_NOT_TERMINAL", "Run has not reached a terminal status")
    actor_id = preferred_string(("actorId", "actor_id", "actId"))
    actor_name = preferred_string(("actorName", "actor_name"))
    count = None
    if structured is not None:
        count = _path_value(structured, ("storages", "datasets", "default", "itemCount"))
    if count is None:
        _has_count, count, _count_path = _first_present(payload, "itemCount")
    item_count = count if isinstance(count, int) and not isinstance(count, bool) else None
    fields = _path_value(structured, ("storages", "datasets", "default", "fields")) if structured is not None else None
    if fields is None:
        _has_fields, fields, _fields_path = _first_present(payload, "fields")
    dataset_fields = tuple(fields) if isinstance(fields, list) and all(isinstance(x, str) for x in fields) else ()
    build_id_value = structured.get("buildId") if structured is not None else None
    build_number_value = structured.get("buildNumber") if structured is not None else None
    if build_id_value is None:
        _has_build_id, build_id_value, _ = _first_present(payload, "buildId")
    if build_number_value is None:
        _has_build_number, build_number_value, _ = _first_present(payload, "buildNumber")
    build_id = str(build_id_value) if build_id_value not in (None, "") else None
    build_number = str(build_number_value) if build_number_value not in (None, "") else None
    build_verified = _build_verification(build_number, build_id,
                                         expected_build_number, expected_build_id)
    cost_value, cost_path = _cost_field(payload)
    raw_fields = tuple(k for k in ("content", "structuredContent", "_meta", "isError") if k in payload)
    return RunMetadata(run_id, actor_id, actor_name, status, dataset_id, dataset_path,
                       item_count, dataset_fields, build_id, build_number, build_verified,
                       source, cost_value, cost_path, raw_fields)


def _decode_dataset_candidates(payload: Mapping[str, Any]) -> list[tuple[str, Any]]:
    candidates: list[tuple[str, Any]] = []
    sc = payload.get("structuredContent")
    if isinstance(sc, Mapping):
        for key in ("items", "data", "results"):
            if key in sc:
                candidates.append((f"structuredContent.{key}", sc[key]))
    elif isinstance(sc, list):
        candidates.append(("structuredContent", sc))
    for i, decoded in enumerate(_json_objects_from_content(payload)):
        if isinstance(decoded, Mapping):
            for key in ("items", "data", "results"):
                if key in decoded:
                    candidates.append((f"content[{i}].text.{key}", decoded[key]))
        elif isinstance(decoded, list):
            candidates.append((f"content[{i}].text", decoded))
    if "structuredContent" not in payload and isinstance(payload.get("result"), list):
        candidates.append(("result", payload["result"]))
    return candidates


def _item_array(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    if not value:
        return value
    if not all(isinstance(item, Mapping) for item in value):
        return None
    # MCP content text blocks are not dataset items, even though they are dicts.
    if all(set(item).issubset({"type", "text"}) and "type" in item for item in value):
        return None
    if not any(any(key in item for key in ("url", "code", "text", "segments", "errMsg")) for item in value):
        return None
    return [dict(item) for item in value]


def dataset_items(payload: Mapping[str, Any], *, expected_dataset_id: str | None = None,
                  expected_run_item_count: int | None = None,
                  allow_incomplete: bool = False,
                  allow_unknown_items: bool = False) -> DatasetPage:
    """Extract actual Dataset items and validate echo/count/page completeness."""
    if response_is_error(payload):
        raise MCPParseError("MCP_TOOL_ERROR", "get-dataset-items returned isError=true")
    candidates = _decode_dataset_candidates(payload)
    chosen: tuple[str, list[dict[str, Any]]] | None = None
    for source, candidate in candidates:
        items = _item_array(candidate)
        if (items is None and allow_unknown_items and isinstance(candidate, list)
                and all(isinstance(item, Mapping) for item in candidate)
                and not all(set(item).issubset({"type", "text"}) and "type" in item for item in candidate)):
            items = [dict(item) for item in candidate]
        if items is not None:
            chosen = source, items
            break
    if chosen is None:
        raise MCPParseError("ITEMS_NOT_FOUND", "No Dataset-shaped item array was present")
    source, items = chosen
    sc = payload.get("structuredContent")
    if not isinstance(sc, Mapping):
        # content-only fallback metadata is the first dataset-shaped decoded object.
        sc = next((obj for obj in _json_objects_from_content(payload)
                   if isinstance(obj, Mapping) and any(k in obj for k in ("items", "data", "results"))), {})
    dataset_id = sc.get("datasetId") if isinstance(sc, Mapping) else None
    if expected_dataset_id and dataset_id != expected_dataset_id:
        raise MCPParseError("DATASET_RUN_BINDING_MISMATCH", "Dataset ID echo did not match the Run")
    item_count = sc.get("itemCount") if isinstance(sc, Mapping) else None
    total = sc.get("totalItemCount") if isinstance(sc, Mapping) else None
    offset = sc.get("offset") if isinstance(sc, Mapping) else None
    limit = sc.get("limit") if isinstance(sc, Mapping) else None
    item_count = item_count if isinstance(item_count, int) and not isinstance(item_count, bool) else None
    total = total if isinstance(total, int) and not isinstance(total, bool) else None
    offset = offset if isinstance(offset, int) and not isinstance(offset, bool) else None
    limit = limit if isinstance(limit, int) and not isinstance(limit, bool) else None
    if item_count is not None and item_count != len(items):
        raise MCPParseError("DATASET_COUNT_MISMATCH", "itemCount does not match the parsed item array")
    if expected_run_item_count is not None and total is not None and total != expected_run_item_count:
        raise MCPParseError("DATASET_RUN_BINDING_MISMATCH", "Run and Dataset item counts disagree")
    complete = None
    if total is not None and offset is not None:
        complete = offset == 0 and len(items) == total
    if offset is not None and offset > 0 and not allow_incomplete:
        raise MCPParseError("INCOMPLETE_DATASET", "A nonzero page offset cannot establish full completeness")
    if complete is False and not allow_incomplete:
        raise MCPParseError("INCOMPLETE_DATASET", "Parsed item count does not cover the Dataset")
    raw_fields = tuple(k for k in ("content", "structuredContent", "_meta", "isError") if k in payload)
    return DatasetPage(dataset_id if isinstance(dataset_id, str) else None, tuple(items),
                       item_count, total, offset, limit, source, complete, raw_fields)


def _shortcode(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]+", raw):
        return raw
    parsed = urlparse(raw)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.hostname.lower() not in ("instagram.com", "www.instagram.com")):
        return None
    match = re.search(r"/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)(?:/|$)", parsed.path, re.IGNORECASE)
    return match.group(1) if match else None


def reel_identity(item: Mapping[str, Any]) -> tuple[str | None, str]:
    """Return URL-derived identity and evidence label; media fields are ignored."""
    urls = [_shortcode(item.get(key)) for key in PAGE_URL_KEYS
            if isinstance(item.get(key), str) and item.get(key).strip()]
    url_ids = {x for x in urls if x}
    if len(url_ids) > 1:
        return None, "identity_conflict"
    if not url_ids:
        return None, "missing"
    identity = next(iter(url_ids))
    codes = [item.get(key).strip() for key in CODE_KEYS
             if isinstance(item.get(key), str) and item.get(key).strip()]
    if any(code != identity for code in codes):
        return identity, "identity_conflict"
    return identity, "url+code" if codes else "url"


def _business_error(item: Mapping[str, Any]) -> str | None:
    for key in ERROR_KEYS:
        if key not in item:
            continue
        value = item[key]
        if value is None or value is False or value == "":
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple)) and not value:
            continue
        if isinstance(value, Mapping) and not value:
            continue
        return scrub(str(value))
    return None


def classify(items: Sequence[Mapping[str, Any]], expected_shortcodes: Sequence[str]) -> dict[str, Any]:
    """Classify expected Reels, duplicates, extras, and business failures."""
    identified: list[tuple[Mapping[str, Any], str | None, str]] = [
        (item, *reel_identity(item)) for item in items
    ]
    expected = list(expected_shortcodes)
    by_code: dict[str, list[tuple[Mapping[str, Any], str]]] = {code: [] for code in expected}
    extras: list[str] = []
    conflicts: set[str] = set()
    for item, identity, evidence in identified:
        if evidence == "identity_conflict" and identity in by_code:
            conflicts.add(identity)
        if identity in by_code:
            by_code[identity].append((item, evidence))
        else:
            extras.append(identity or "unidentified")
    results: list[ReelResult] = []
    for code in expected:
        matches = by_code[code]
        if len(matches) > 1:
            duplicate_errors = [_business_error(item) for item, _evidence in matches]
            duplicate_error = "; ".join(error for error in duplicate_errors if error) or None
            results.append(ReelResult(code, "duplicate_matches", None, None, None, duplicate_error,
                                      len(matches), tuple(sorted(matches[0][0].keys()))))
            continue
        if not matches:
            results.append(ReelResult(code, "missing", None, None, None, None, 0))
            continue
        item, evidence = matches[0]
        error = _business_error(item)
        if evidence == "identity_conflict" or code in conflicts:
            match = "identity_conflict"
        elif error is not None:
            match = "business_error"
        else:
            match = "matched"
        text = item.get("text")
        transcript = isinstance(text, str) and bool(text.strip())
        segments = item.get("segments")
        segments_count = len(segments) if isinstance(segments, list) else None
        results.append(ReelResult(code, match, transcript, segments_count, evidence,
                                  error, 1, tuple(sorted(item.keys()))))
    extra_details: list[dict[str, Any]] = []
    for item, identity, evidence in identified:
        if identity not in by_code:
            extra_details.append({"identity": identity, "businessError": _business_error(item),
                                  "itemKeys": sorted(str(key) for key in item.keys())})
    business_errors = sum(r.business_error is not None for r in results) + sum(
        item["businessError"] is not None for item in extra_details)
    verdict = "PASS" if (all(r.match == "matched" and r.transcript_present is True
                              and isinstance(r.segments_count, int) and r.segments_count > 0 for r in results)
                          and not extras and business_errors == 0 and len(expected) > 0) else "PARTIAL"
    return {"results": [r.to_dict() for r in results], "extras": extras,
            "extraDetails": extra_details, "businessErrors": business_errors, "verdict": verdict}


def creation_transport_outcome(*, request_sent: bool, response_received: bool) -> str:
    """A sent create request with no response has an unknown, non-retriable outcome."""
    if request_sent and not response_received:
        return "OUTCOME_UNKNOWN"
    if request_sent and response_received:
        return "RESPONSE_RECEIVED"
    return "NOT_SENT"


def acceptance(run: RunMetadata, page: DatasetPage,
               expected_shortcodes: Sequence[str], *,
               expected_build_number: str | None = None,
               expected_build_id: str | None = None) -> dict[str, Any]:
    """Combine independently validated run and Dataset evidence into a report model."""
    if not isinstance(run.run_id, str) or not run.run_id.strip():
        raise MCPParseError("RUN_IDENTITY_UNAVAILABLE", "Acceptance requires a verified Run identity")
    if run.status is None or run.status.upper() not in TERMINAL_STATUSES:
        raise MCPParseError("RUN_NOT_TERMINAL", "A terminal, identified Run is required")
    if (not isinstance(run.dataset_id, str) or not run.dataset_id.strip()
            or not isinstance(page.dataset_id, str) or not page.dataset_id.strip()):
        raise MCPParseError("DATASET_RUN_BINDING_MISMATCH", "Run and Dataset identities are both required")
    if run.dataset_id != page.dataset_id:
        raise MCPParseError("DATASET_RUN_BINDING_MISMATCH", "Dataset ID echo differs from Run metadata")
    if page.complete is not True:
        raise MCPParseError("INCOMPLETE_DATASET", "Dataset completeness was not verified")
    if run.dataset_item_count is not None and page.total_item_count is not None:
        if run.dataset_item_count != page.total_item_count:
            raise MCPParseError("DATASET_RUN_BINDING_MISMATCH", "Run and Dataset item counts disagree")
    result = classify(page.items, expected_shortcodes)
    functional_verdict = result["verdict"]
    if run.status.upper() != "SUCCEEDED":
        functional_verdict = "PARTIAL"
    build_verified = _build_verification(run.build_number, run.build_id,
                                         expected_build_number, expected_build_id)
    if run.build_verified == "BUILD_DRIFT":
        build_verified = "BUILD_DRIFT"
    verdict = "BUILD_DRIFT" if build_verified == "BUILD_DRIFT" else functional_verdict
    result.update({"functionalVerdict": functional_verdict, "verdict": verdict,
                   "runSource": run.run_source, "datasetSource": "get-dataset-items",
                   "datasetIdPath": run.dataset_id_path, "buildVerified": build_verified,
                   "itemCount": page.item_count, "totalItemCount": page.total_item_count,
                   "parsedItems": len(page.items), "costValue": run.cost_value,
                   "costPath": run.cost_path, "complete": page.complete,
                   "costStatus": "OBSERVED" if run.cost_value is not None else "UNKNOWN",
                   "costCapStatus": "NOT_VERIFIED"})
    return result


_PROFILE_USERNAME = re.compile(r"^[^\s@/]+$")
_PROFILE_POST_URL = re.compile(r"^/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)(?:/|$)", re.IGNORECASE)
_PROFILE_CODE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_profile_input(usernames: Any, *, results_limit: Any = None,
                           skip_pinned_posts: Any = None) -> ProfileInput:
    """Validate only client-side safety constraints; never claims schema defaults."""
    if not isinstance(usernames, (list, tuple)) or not usernames:
        raise MCPParseError("PROFILE_INPUT_INVALID", "usernames must be a nonempty array")
    raw_names: list[str] = []
    comparison: list[str] = []
    for name in usernames:
        if not isinstance(name, str) or not name or name != name.strip() or not _PROFILE_USERNAME.fullmatch(name):
            raise MCPParseError("PROFILE_INPUT_INVALID", "each username must be a nonempty explicit account name")
        raw_names.append(name)
        comparison.append(name.casefold())
    if len(set(comparison)) != len(comparison):
        raise MCPParseError("PROFILE_USERNAME_AMBIGUOUS", "usernames are duplicated or ambiguous under conservative case-fold comparison")
    if results_limit is not None and (isinstance(results_limit, bool) or not isinstance(results_limit, int)
                                     or results_limit <= 0):
        raise MCPParseError("PROFILE_INPUT_INVALID", "resultsLimit must be a positive integer when supplied")
    if skip_pinned_posts is not None and not isinstance(skip_pinned_posts, bool):
        raise MCPParseError("PROFILE_INPUT_INVALID", "skipPinnedPosts must be a Boolean when supplied")
    # Comparison keys are used only to reject ambiguous inputs. Attribution below
    # requires exact string equality; case folding is not an equivalence rule.
    return ProfileInput(tuple(raw_names), tuple(comparison), results_limit, skip_pinned_posts)


def _profile_text_state(item: Mapping[str, Any]) -> str:
    if "text" not in item:
        return "MISSING"
    value = item["text"]
    if value is None:
        return "NULL"
    if not isinstance(value, str):
        return "UNSUPPORTED_TYPE"
    if not value:
        return "EMPTY"
    if not value.strip():
        return "WHITESPACE_ONLY"
    return "NONEMPTY_STRING"


def _profile_segments_state(item: Mapping[str, Any]) -> tuple[str, int | None]:
    if "segments" not in item:
        return "MISSING", None
    value = item["segments"]
    if value is None:
        return "NULL", None
    if not isinstance(value, list):
        return "UNSUPPORTED_TYPE", None
    return ("NONEMPTY_ARRAY", len(value)) if value else ("EMPTY_ARRAY", 0)


def _profile_error_state(item: Mapping[str, Any]) -> tuple[str, str, bool, str | None]:
    if "errMsg" not in item:
        return "MISSING", "MISSING", False, None
    value = item["errMsg"]
    if value is None:
        return "EMPTY", "NULL", False, None
    if isinstance(value, str):
        if not value:
            return "EMPTY", "EMPTY", False, None
        if not value.strip():
            return "EMPTY", "WHITESPACE_ONLY", True, None
        return "NONEMPTY", "NONEMPTY", False, scrub(value)
    return "UNSUPPORTED_TYPE", "UNSUPPORTED_TYPE", False, None


def _profile_business_errors(item: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...],
                                                               tuple[tuple[str, str], ...], bool]:
    sources: list[str] = []
    messages: list[str] = []
    states: list[tuple[str, str]] = []
    for key in ERROR_KEYS:
        if key not in item:
            state = "MISSING"
        else:
            value = item[key]
            if value is None:
                state = "NULL"
            elif isinstance(value, str) and value == "":
                state = "EMPTY"
            elif isinstance(value, str) and not value.strip():
                state = "WHITESPACE_ONLY"
            elif isinstance(value, str):
                state = "NONEMPTY"
                sources.append(key)
                messages.append(scrub(value))
            else:
                state = "UNSUPPORTED_TYPE"
        states.append((key, state))
    return tuple(sources), tuple(messages), tuple(states), len(set(messages)) > 1


def _profile_post_url_code(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.hostname.lower() not in ("instagram.com", "www.instagram.com")):
        return None
    match = _PROFILE_POST_URL.match(parsed.path)
    return match.group(1) if match else None


def _profile_identity(item: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    supplied_code = item.get("code")
    valid_code = supplied_code.strip() if isinstance(supplied_code, str) and supplied_code.strip() else None
    if valid_code is not None and not _PROFILE_CODE.fullmatch(valid_code):
        valid_code = None
    url = item.get("url")
    url_code = _profile_post_url_code(url)
    if valid_code and url_code and valid_code != url_code:
        return "POST_IDENTITY_CONFLICT", ()
    code = valid_code or url_code
    keys: list[str] = [f"code:{code}"] if code else []
    # pk and id are separate namespaces: their semantic equivalence is unverified.
    for key in ("pk", "id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            keys.append(f"{key}:{value.strip()}")
        elif isinstance(value, int) and not isinstance(value, bool):
            keys.append(f"{key}:{value}")
    if keys:
        return "IDENTIFIED", tuple(dict.fromkeys(keys))
    if isinstance(url, str) and url and _profile_post_url_code(url) is None:
        try:
            parsed = urlparse(url)
            if (parsed.scheme in ("http", "https") and parsed.hostname
                    and parsed.hostname.lower() in ("instagram.com", "www.instagram.com")):
                path_parts = [part for part in parsed.path.split("/") if part]
                if len(path_parts) == 1:
                    return "PROFILE_PAGE_URL_ONLY", ()
        except ValueError:
            pass
    return "UNAVAILABLE", ()


def profile_item(item: Mapping[str, Any], requested_usernames: Sequence[str]) -> ProfileItemResult:
    """Summarize one Profile item without retaining caption/transcript content."""
    context = validate_profile_input(requested_usernames)
    owner_value = item.get("ownerUsername")
    if "ownerUsername" not in item:
        owner_field_state = "ABSENT"
    elif not isinstance(owner_value, str):
        owner_field_state = "INVALID_TYPE"
    elif not owner_value:
        owner_field_state = "EMPTY"
    elif owner_value != owner_value.strip():
        owner_field_state = "INVALID_VALUE"
    else:
        owner_field_state = "PRESENT"
    owner = owner_value if owner_field_state == "PRESENT" else None
    author_value = item.get("userName")
    author = author_value if isinstance(author_value, str) and author_value else None
    author_conflict = bool(owner and author and owner != author)
    if "ownerUsername" not in item:
        attribution = "CONTEXT_ONLY_UNCONFIRMED" if len(context.usernames) == 1 else "OWNER_UNAVAILABLE"
        requested_owner = context.usernames[0] if len(context.usernames) == 1 else None
    elif owner is None:
        attribution, requested_owner = "OWNER_AMBIGUOUS", None
    elif owner in context.usernames:
        attribution, requested_owner = "MATCHED_OWNER", owner
    elif owner.casefold() in context.normalized_usernames:
        attribution, requested_owner = "OWNER_AMBIGUOUS", None
    else:
        attribution, requested_owner = "OWNER_MISMATCH", None

    post_identity, post_keys = _profile_identity(item)
    text_state = _profile_text_state(item)
    segments_state, segments_count = _profile_segments_state(item)
    err_state, err_state_detail, err_whitespace, err_msg = _profile_error_state(item)
    error_sources, error_messages, error_field_states, error_conflict = _profile_business_errors(item)
    business_error = (scrub("; ".join(f"{key}: {message}"
                                      for key, message in zip(error_sources, error_messages)))
                      if error_sources else None)
    transcript_states = (text_state, segments_state)
    if "UNSUPPORTED_TYPE" in transcript_states:
        transcript_data_state = "MALFORMED"
    elif text_state == "NONEMPTY_STRING" or segments_state == "NONEMPTY_ARRAY":
        transcript_data_state = "PRESENT"
    else:
        transcript_data_state = "ABSENT"
    post_markers = (post_identity == "IDENTIFIED" or any(key in item for key in (
        "type", "caption", "commentsCount", "videoPlayCount", "videoDuration", "hashtags", "mentions")))
    if business_error is not None:
        status = "ACTOR_ITEM_ERROR"
    elif any(state == "UNSUPPORTED_TYPE" for _key, state in error_field_states):
        status = "UNKNOWN_SHAPE"
    elif post_identity == "POST_IDENTITY_CONFLICT":
        status = "POST_IDENTITY_CONFLICT"
    elif not post_markers:
        status = "UNKNOWN_SHAPE"
    elif attribution != "MATCHED_OWNER":
        status = attribution
    else:
        status = "PROFILE_POST_MATCHED"
    # An unsupported transcript field is kept as a dimension; it does not make
    # valid Profile metadata fail because transcript is not a Profile requirement.
    return ProfileItemResult(
        status=status, requested_owner=requested_owner, owner_username=owner,
        owner_field_state=owner_field_state,
        attribution=attribution, author_field_conflict=author_conflict,
        post_identity=post_identity, post_keys=post_keys,
        duplicate_status="NOT_VERIFIABLE", text_state=text_state,
        segments_state=segments_state, segments_count=segments_count,
        err_msg_state=err_state, err_msg_state_detail=err_state_detail,
        err_msg_whitespace_only=err_whitespace, business_error=business_error,
        business_error_sources=error_sources, business_error_messages=error_messages,
        business_error_field_states=error_field_states, business_error_conflict=error_conflict,
        transcript_assessment="NOT_EXPECTED_PROFILE_MODE",
        transcript_data_state=transcript_data_state,
        item_keys=tuple(sorted(str(key) for key in item.keys())),
    )


def profile_page_ledger(pages: Sequence[DatasetPage], *, expected_dataset_id: str) -> ProfilePageLedger:
    """Merge already parsed Dataset pages and prove Dataset-page completeness conservatively."""
    if not pages:
        raise MCPParseError("ITEMS_UNAVAILABLE", "No Dataset page was supplied")
    if not isinstance(expected_dataset_id, str) or not expected_dataset_id.strip():
        raise MCPParseError("DATASET_ID_UNAVAILABLE", "Profile acceptance requires a Dataset ID")
    if any(page.dataset_id != expected_dataset_id for page in pages):
        raise MCPParseError("DATASET_RUN_BINDING_MISMATCH", "Profile Dataset page echo differs from Run metadata")
    totals = {page.total_item_count for page in pages if page.total_item_count is not None}
    if len(totals) > 1:
        raise MCPParseError("DATASET_COUNT_MISMATCH", "Dataset pages report conflicting total counts")
    offsets = tuple(page.offset for page in pages)
    if any(offset is None or offset < 0 for offset in offsets):
        return ProfilePageLedger(expected_dataset_id, tuple(item for page in pages for item in page.items),
                                 len(pages), "COMPLETENESS_UNKNOWN", next(iter(totals), None),
                                 sum(len(page.items) for page in pages), offsets)
    if len(set(offsets)) != len(offsets):
        raise MCPParseError("DATASET_PAGE_OVERLAP", "Dataset pages repeat an offset")
    ordered = sorted(pages, key=lambda page: page.offset if page.offset is not None else -1)
    total = next(iter(totals), None)
    cursor = 0
    for page in ordered:
        assert page.offset is not None
        if page.offset != cursor:
            return ProfilePageLedger(expected_dataset_id, tuple(item for p in ordered for item in p.items),
                                     len(ordered), "INCOMPLETE", total,
                                     sum(len(p.items) for p in ordered), offsets)
        end = page.offset + len(page.items)
        cursor = end
    item_count = sum(len(page.items) for page in ordered)
    if total is None:
        completeness = "COMPLETENESS_UNKNOWN"
    elif cursor == total:
        completeness = "COMPLETE"
    elif cursor < total:
        completeness = "INCOMPLETE"
    else:
        raise MCPParseError("DATASET_COUNT_MISMATCH", "Parsed pages exceed the reported Dataset total")
    return ProfilePageLedger(expected_dataset_id, tuple(item for page in ordered for item in page.items),
                             len(ordered), completeness, total, item_count, offsets)


def _profile_duplicate_states(results: Sequence[ProfileItemResult]) -> list[ProfileItemResult]:
    seen: dict[tuple[str, str], list[int]] = {}
    for index, result in enumerate(results):
        if result.attribution != "MATCHED_OWNER":
            continue
        for key in result.post_keys:
            seen.setdefault((result.owner_username or "", key), []).append(index)
    duplicates = {index for indexes in seen.values() if len(indexes) > 1 for index in indexes}
    updated: list[ProfileItemResult] = []
    for index, result in enumerate(results):
        if index in duplicates:
            state = "DUPLICATE"
        elif result.attribution == "MATCHED_OWNER" and result.post_keys:
            state = "UNIQUE"
        else:
            state = "NOT_VERIFIABLE"
        updated.append(ProfileItemResult(**{**asdict(result), "duplicate_status": state}))
    return updated


def profile_acceptance(run: RunMetadata, pages: Sequence[DatasetPage], usernames: Any, *,
                       results_limit: Any = None, skip_pinned_posts: Any = None) -> dict[str, Any]:
    """Profile-only acceptance; Run/Dataset and transcript states stay independent."""
    profile_input = validate_profile_input(usernames, results_limit=results_limit,
                                           skip_pinned_posts=skip_pinned_posts)
    if not isinstance(run.run_id, str) or not run.run_id.strip():
        raise MCPParseError("RUN_IDENTITY_UNAVAILABLE", "Profile acceptance requires a verified Run identity")
    if run.status is None or run.status.upper() not in TERMINAL_STATUSES:
        raise MCPParseError("RUN_NOT_TERMINAL", "A terminal, identified Run is required")
    if run.status.upper() != "SUCCEEDED":
        return {"status": "RUN_FAILED", "functionalVerdict": "PARTIAL", "verdict": "PARTIAL",
                "blockingReasons": ["RUN_FAILED"], "overallBlockingReasons": ["RUN_FAILED"],
                "items": [], "runStatus": run.status, "datasetCompleteness": "NOT_READ",
                "datasetIdPath": run.dataset_id_path or "UNKNOWN", "itemsSource": "UNKNOWN",
                "datasetSource": "UNKNOWN", "runSource": run.run_source or "UNKNOWN",
                "itemCount": None, "totalItemCount": None, "parsedItemCount": 0,
                "ownerFieldAbsentCount": 0, "ownerPresenceByAccount": [],
                "transcriptRequired": False, "transcriptAssessment": "NOT_EXPECTED_PROFILE_MODE",
                "transcriptDataState": "NOT_READ"}
    if not isinstance(run.dataset_id, str) or not run.dataset_id.strip():
        raise MCPParseError("DATASET_RUN_BINDING_MISMATCH", "Run Dataset identity is required")
    ledger = profile_page_ledger(pages, expected_dataset_id=run.dataset_id)
    if run.dataset_item_count is not None and ledger.total_item_count is not None:
        if run.dataset_item_count != ledger.total_item_count:
            raise MCPParseError("DATASET_RUN_BINDING_MISMATCH", "Run and Dataset item counts disagree")
    parsed = [profile_item(item, profile_input.usernames) for item in ledger.items]
    results = _profile_duplicate_states(parsed)
    matched_owners = {item.owner_username for item in results
                      if item.attribution == "MATCHED_OWNER" and item.status == "PROFILE_POST_MATCHED"}
    every_requested_account_seen = all(name in matched_owners for name in profile_input.usernames)
    all_items_matched = all(item.status == "PROFILE_POST_MATCHED" for item in results)

    account_counts = {name: {"recordCount": 0, "ownerFieldPresentCount": 0,
                             "ownerFieldAbsentCount": 0, "ownerFieldTypeErrorCount": 0,
                             "ownerFieldEmptyCount": 0, "ownerMismatchCount": 0,
                             "ownerAmbiguousCount": 0, "trustedOwnerMatchCount": 0,
                             "contextOnlyCount": 0}
                      for name in profile_input.usernames}
    for item in results:
        if item.attribution == "MATCHED_OWNER" and item.owner_username in account_counts:
            counters = account_counts[item.owner_username]
            counters["recordCount"] += 1
            counters["ownerFieldPresentCount"] += 1
            counters["trustedOwnerMatchCount"] += 1
        elif item.attribution == "CONTEXT_ONLY_UNCONFIRMED" and item.requested_owner in account_counts:
            counters = account_counts[item.requested_owner]
            counters["recordCount"] += 1
            counters["ownerFieldAbsentCount"] += 1
            counters["contextOnlyCount"] += 1
        elif item.attribution == "OWNER_AMBIGUOUS" and item.owner_username:
            account_name = next((name for name in profile_input.usernames
                                 if name.casefold() == item.owner_username.casefold()), None)
            if account_name is not None:
                account_counts[account_name]["ownerAmbiguousCount"] += 1
    accounts_without_posts = ([name for name, counters in account_counts.items()
                               if counters["trustedOwnerMatchCount"] == 0]
                              if ledger.completeness == "COMPLETE" else [])
    owner_field_absent_count = sum(item.owner_field_state == "ABSENT" for item in results)
    owner_field_type_error_count = sum(item.owner_field_state in ("INVALID_TYPE", "INVALID_VALUE")
                                       for item in results)
    owner_field_empty_count = sum(item.owner_field_state == "EMPTY" for item in results)
    owner_field_present_count = sum(item.owner_field_state == "PRESENT" for item in results)
    owner_mismatch_count = sum(item.attribution == "OWNER_MISMATCH" for item in results)
    owner_ambiguous_count = sum(item.attribution == "OWNER_AMBIGUOUS" for item in results)
    context_only_count = sum(item.attribution == "CONTEXT_ONLY_UNCONFIRMED" for item in results)
    author_conflict_count = sum(item.author_field_conflict for item in results)

    blocking_reasons: list[str] = []
    def block(reason: str, condition: bool) -> None:
        if condition and reason not in blocking_reasons:
            blocking_reasons.append(reason)

    block("ACTOR_ITEM_ERROR", any(item.business_error is not None for item in results))
    block("INCOMPLETE", ledger.completeness == "INCOMPLETE")
    block("COMPLETENESS_UNKNOWN", ledger.completeness == "COMPLETENESS_UNKNOWN")
    block("OWNER_MISMATCH", owner_mismatch_count > 0)
    block("OWNER_AMBIGUOUS", owner_ambiguous_count > 0)
    block("OWNER_UNAVAILABLE", any(item.attribution == "OWNER_UNAVAILABLE" for item in results))
    block("CONTEXT_ONLY_UNCONFIRMED", context_only_count > 0)
    block("REQUESTED_ACCOUNT_WITHOUT_POST", bool(accounts_without_posts))
    block("AUTHOR_FIELD_CONFLICT", author_conflict_count > 0)
    block("POST_IDENTITY_CONFLICT", any(item.post_identity == "POST_IDENTITY_CONFLICT" for item in results))
    block("UNKNOWN_SHAPE", any(item.status == "UNKNOWN_SHAPE" for item in results))
    block("DUPLICATE_PROFILE_POST", any(item.duplicate_status == "DUPLICATE" for item in results))
    block("DUPLICATE_CHECK_NOT_VERIFIABLE",
          any(item.duplicate_status == "NOT_VERIFIABLE" for item in results))
    block("EMPTY_PROFILE_RESULT", not ledger.items and ledger.completeness == "COMPLETE")

    strict_pass = (run.status.upper() == "SUCCEEDED" and ledger.completeness == "COMPLETE"
                   and bool(results) and every_requested_account_seen and all_items_matched
                   and all(item.duplicate_status == "UNIQUE" for item in results)
                   and author_conflict_count == 0)
    functional = "PASS" if strict_pass else (
        "COMPLETENESS_UNKNOWN" if ledger.completeness == "COMPLETENESS_UNKNOWN" else "PARTIAL")
    build = run.build_verified
    verdict = "BUILD_DRIFT" if build == "BUILD_DRIFT" else functional
    if strict_pass:
        status = "PROFILE_POST_MATCHED"
    else:
        priority = ("ACTOR_ITEM_ERROR", "INCOMPLETE", "COMPLETENESS_UNKNOWN", "OWNER_MISMATCH",
                    "OWNER_AMBIGUOUS", "OWNER_UNAVAILABLE", "UNKNOWN_SHAPE",
                    "POST_IDENTITY_CONFLICT", "AUTHOR_FIELD_CONFLICT", "CONTEXT_ONLY_UNCONFIRMED",
                    "EMPTY_PROFILE_RESULT", "REQUESTED_ACCOUNT_WITHOUT_POST",
                    "DUPLICATE_PROFILE_POST", "DUPLICATE_CHECK_NOT_VERIFIABLE")
        status = next((reason for reason in priority if reason in blocking_reasons), "ACCEPTANCE_INCOMPLETE")

    observed_items_sources = sorted({page.items_source for page in pages if page.items_source})
    if not observed_items_sources:
        items_source: str | list[str] = "UNKNOWN"
    elif len(observed_items_sources) == 1:
        items_source = observed_items_sources[0]
    else:
        items_source = observed_items_sources
    dataset_envelope_observed = any(
        "structuredContent" in page.raw_fields_present or "content" in page.raw_fields_present
        for page in pages
    )
    dataset_source = "MCP" if dataset_envelope_observed and observed_items_sources else "UNKNOWN"
    observed_item_counts = [page.item_count for page in pages]
    item_count = sum(observed_item_counts) if all(count is not None for count in observed_item_counts) else None
    dataset_raw_fields = sorted({key for page in pages for key in page.raw_fields_present})
    return {
        "status": status, "statusScope": "AGGREGATE",
        "functionalVerdict": functional, "verdict": verdict,
        "blockingReasons": blocking_reasons,
        "overallBlockingReasons": (["BUILD_DRIFT"] if build == "BUILD_DRIFT" else blocking_reasons),
        "runStatus": run.status, "runId": run.run_id, "datasetId": ledger.dataset_id,
        "datasetIdPath": run.dataset_id_path or "UNKNOWN",
        "itemsSource": items_source, "datasetSource": dataset_source, "runSource": run.run_source or "UNKNOWN",
        "runRawFieldsPresent": list(run.raw_fields_present),
        "datasetRawFieldsPresent": dataset_raw_fields,
        "datasetCompleteness": ledger.completeness,
        "itemCount": item_count, "totalItemCount": ledger.total_item_count,
        "parsedItemCount": ledger.parsed_item_count, "datasetItemCount": ledger.total_item_count,
        "pageCount": ledger.page_count,
        "pageOffsets": list(ledger.offsets), "accountContentCoverage": "UNVERIFIED",
        "requestedAccounts": list(profile_input.usernames),
        "matchedAccounts": sorted(name for name in matched_owners if name is not None),
        "allRequestedAccountsSeen": every_requested_account_seen,
        "requestedAccountsWithoutPost": accounts_without_posts,
        "ownerFieldPresentCount": owner_field_present_count,
        "ownerFieldAbsentCount": owner_field_absent_count,
        "ownerFieldTypeErrorCount": owner_field_type_error_count,
        "ownerFieldEmptyCount": owner_field_empty_count,
        "ownerMismatchCount": owner_mismatch_count,
        "ownerAmbiguousCount": owner_ambiguous_count,
        "contextOnlyUnconfirmedCount": context_only_count,
        "authorFieldConflictCount": author_conflict_count,
        "ownerPresenceByAccount": [
            {"requestedUsername": name, **counters} for name, counters in account_counts.items()
        ],
        "resultsLimit": profile_input.results_limit,
        "skipPinnedPosts": profile_input.skip_pinned_posts,
        "transcriptRequired": False,
        "transcriptAssessment": "NOT_EXPECTED_PROFILE_MODE",
        "transcriptDataState": "OBSERVED" if results else "ABSENT",
        "transcriptDataStates": sorted({item.transcript_data_state for item in results}),
        "items": [item.to_dict() for item in results], "buildVerified": build,
        "costCapStatus": "NOT_VERIFIED",
    }


def scrub(value: str) -> str:
    """Remove likely credentials and URLs before placing error text in reports."""
    value = re.sub(r"(?i)Bearer\s+[^\s\"']+", "Bearer [REDACTED]", value)
    value = re.sub(r"(?i)(authorization\s*[:=]\s*)[^\r\n]+", r"\1[REDACTED]", value)
    value = re.sub(r"https?://\S+", "[URL REDACTED]", value)
    value = re.sub(r"(?i)(?:apify_api_)?[A-Za-z0-9_-]{20,}", "[VALUE REDACTED]", value)
    return value[:300]
