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
                  expected_run_item_count: int | None = None) -> DatasetPage:
    """Extract actual Dataset items and validate echo/count/page completeness."""
    if response_is_error(payload):
        raise MCPParseError("MCP_TOOL_ERROR", "get-dataset-items returned isError=true")
    candidates = _decode_dataset_candidates(payload)
    chosen: tuple[str, list[dict[str, Any]]] | None = None
    for source, candidate in candidates:
        items = _item_array(candidate)
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
    if offset is not None and offset > 0:
        raise MCPParseError("INCOMPLETE_DATASET", "A nonzero page offset cannot establish full completeness")
    if complete is False:
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


def scrub(value: str) -> str:
    """Remove likely credentials and URLs before placing error text in reports."""
    value = re.sub(r"(?i)Bearer\s+[^\s\"']+", "Bearer [REDACTED]", value)
    value = re.sub(r"(?i)(authorization\s*[:=]\s*)[^\r\n]+", r"\1[REDACTED]", value)
    value = re.sub(r"https?://\S+", "[URL REDACTED]", value)
    value = re.sub(r"(?i)(?:apify_api_)?[A-Za-z0-9_-]{20,}", "[VALUE REDACTED]", value)
    return value[:300]
