#!/usr/bin/env python3
"""Read-only audit of the one authorized existing Actor Run and its Dataset."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.check_apify_usage import UsageCheckError, fetch_usage, write_private_json

ROOT = Path(__file__).resolve().parents[1]
API_BASE = "https://api.apify.com/v2"
DATASET_PAGE_LIMIT = 1000
SENSITIVE_PARTS = ("token", "authorization", "cookie", "password", "secret", "session", "email")


class LiveAuditError(Exception):
    """Safe-to-display error without response body, headers, or credentials."""


def _safe_field_name(value: Any) -> str:
    name = str(value)
    compact = re.sub(r"[^a-z0-9]", "", name.lower())
    if any(part in compact for part in SENSITIVE_PARTS):
        return "[redacted-field]"
    return name[:120]


def _request_json(path: str, token: str, *, opener: Callable[..., Any] | None = None) -> tuple[Any, Any]:
    if not path.startswith("/") or path.startswith("//"):
        raise LiveAuditError("Refusing a non-relative Apify API path")
    request = urllib.request.Request(
        API_BASE + path,
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        method="GET",
    )
    open_request = opener or urllib.request.urlopen
    try:
        with open_request(request, timeout=30) as response:
            raw = response.read()
            status = getattr(response, "status", 200)
            headers = getattr(response, "headers", {})
            if status < 200 or status >= 300:
                raise LiveAuditError(f"Apify GET returned HTTP {status}")
    except urllib.error.HTTPError as exc:
        raise LiveAuditError(f"Apify GET returned HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise LiveAuditError(f"Apify GET network failure ({type(exc.reason).__name__})") from None
    except (TimeoutError, OSError) as exc:
        raise LiveAuditError(f"Apify GET network failure ({type(exc).__name__})") from None
    try:
        return json.loads(raw.decode("utf-8")), headers
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise LiveAuditError("Apify GET response was not valid UTF-8 JSON") from None


def _unwrap_data(payload: Any, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise LiveAuditError(f"{label} GET response had an unexpected JSON structure")
    return payload["data"]


def _summarize_charge_fields(run: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("usageTotalUsd", "chargedEventCounts"):
        if key not in run:
            result[key] = {"state": "missing"}
            continue
        value = run[key]
        if value is None:
            result[key] = {"state": "null; not treated as zero"}
        elif key == "usageTotalUsd" and isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = {"state": "reported", "value": value}
        elif key == "chargedEventCounts" and isinstance(value, dict):
            result[key] = {
                "state": "reported",
                "value": {_safe_field_name(name): count for name, count in value.items()
                          if isinstance(count, (int, float)) and not isinstance(count, bool)},
                "unparsedFieldNames": [_safe_field_name(name) for name, count in value.items()
                                       if not isinstance(count, (int, float)) or isinstance(count, bool)],
            }
        else:
            result[key] = {"state": "present with unrecognized type", "type": _json_type(value)}
    excluded = {"usageTotalUsd", "chargedEventCounts"}
    related = [
        _safe_field_name(key) for key in run
        if key not in excluded and re.search(r"usage|charge|cost|event|price|billing", str(key), re.I)
    ]
    result["otherChargeRelatedFieldNames"] = related
    return result


def _json_type(value: Any) -> str:
    if value is None: return "null"
    if isinstance(value, bool): return "boolean"
    if isinstance(value, (int, float)): return "number"
    if isinstance(value, str): return "string"
    if isinstance(value, list): return "array"
    if isinstance(value, dict): return "object"
    return "unknown"


def _summarize_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"itemType": _json_type(item), "fieldNames": []}
    text_present = "text" in item
    text = item.get("text")
    segments_present = "segments" in item
    segments = item.get("segments")
    error_present = "errMsg" in item
    error = item.get("errMsg")
    if isinstance(segments, (list, dict, str)):
        segments_count: int | None = len(segments)
    else:
        segments_count = None
    return {
        "fieldNames": sorted(_safe_field_name(key) for key in item),
        "text": {
            "present": text_present,
            "type": _json_type(text) if text_present else "missing",
            "nonEmpty": isinstance(text, str) and bool(text.strip()),
        },
        "segments": {
            "present": segments_present,
            "type": _json_type(segments) if segments_present else "missing",
            "count": segments_count,
        },
        "errMsg": {
            "present": error_present,
            "type": _json_type(error) if error_present else "missing",
            "nonEmpty": error is not None and bool(str(error).strip()),
        },
    }


def _validate_identifier(value: str, label: str, *, path_segment: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiveAuditError(f"{label} is required")
    value = value.strip()
    if path_segment and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise LiveAuditError(f"{label} has an invalid format")
    return value


def collect_live_audit(
    token: str,
    *,
    run_id: str,
    dataset_id: str,
    actor_id: str,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if not token or not token.strip():
        raise LiveAuditError("APIFY_TOKEN is missing; no request was sent")

    run_id = _validate_identifier(run_id, "Run ID", path_segment=True)
    dataset_id = _validate_identifier(dataset_id, "Dataset ID", path_segment=True)
    actor_id = _validate_identifier(actor_id, "Actor ID")

    run_payload, _ = _request_json(f"/actor-runs/{run_id}", token.strip(), opener=opener)
    run = _unwrap_data(run_payload, "Run")
    if run.get("id") != run_id:
        raise LiveAuditError("Run response ID did not match the requested Run ID; stopped")
    actor_value = run.get("actId", run.get("actorId"))
    if actor_value != actor_id:
        raise LiveAuditError("Run Actor ID was missing or did not match the requested Actor ID; stopped")
    run_dataset_id = run.get("defaultDatasetId")
    if run_dataset_id != dataset_id:
        raise LiveAuditError("Run Dataset ID was missing or did not match the requested Dataset ID; stopped")

    status = run.get("status")
    dataset_summary: dict[str, Any] = {"datasetId": dataset_id, "itemsReturned": None, "totalItemCount": "unknown"}
    if status == "SUCCEEDED":
        query = urllib.parse.urlencode({"limit": DATASET_PAGE_LIMIT, "offset": 0})
        dataset_payload, _ = _request_json(f"/datasets/{dataset_id}/items?{query}", token.strip(), opener=opener)
        if not isinstance(dataset_payload, list):
            raise LiveAuditError("Dataset items GET response was not a JSON array")
        dataset_summary["itemsReturned"] = len(dataset_payload)
        dataset_summary["items"] = [_summarize_item(item) for item in dataset_payload]
        dataset_summary["totalItemCount"] = "unknown; only returned page count is asserted"
    else:
        dataset_summary["readState"] = "skipped because Run status was not SUCCEEDED"

    try:
        usage_summary = fetch_usage(token.strip(), opener=opener)
        usage_state: dict[str, Any] = {"state": "read", "summary": usage_summary}
    except UsageCheckError as exc:
        usage_state = {"state": "unavailable", "error": str(exc)}

    return {
        "checkedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run": {
            "runId": run.get("id"),
            "actorId": actor_value,
            "buildId": run.get("buildId", "unknown; field not returned"),
            "buildNumber": run.get("buildNumber", run.get("buildVersion", "unknown; field not returned")),
            "terminalStatus": status if status in {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"} else "not-terminal-or-unknown",
            "statusField": status if isinstance(status, str) else "unknown",
            "datasetId": dataset_id,
            "charges": _summarize_charge_fields(run),
        },
        "dataset": dataset_summary,
        "monthlyUsage": usage_state,
        "interpretation": {
            "missingOrNullCharge": "unknown, never converted to zero",
            "usageDifference": "not calculated or attributed to this Run",
            "transcript": "content omitted; only field/type/non-empty checks are reported",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _validate_identifier(args.run_id, "Run ID", path_segment=True)
        _validate_identifier(args.dataset_id, "Dataset ID", path_segment=True)
        _validate_identifier(args.actor_id, "Actor ID")
    except LiveAuditError as exc:
        parser.error(str(exc))
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        print("Error: python-dotenv is required to load the repository .env file", file=sys.stderr)
        return 2
    token = os.getenv("APIFY_TOKEN")
    try:
        result = collect_live_audit(
            token or "", run_id=args.run_id, dataset_id=args.dataset_id, actor_id=args.actor_id
        )
        if args.output:
            write_private_json(args.output, result)
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 0
    except LiveAuditError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except UsageCheckError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only audit of one explicitly identified Actor Run; never creates Runs.")
    parser.add_argument("--run-id", required=True, help="existing Run ID to inspect (GET only)")
    parser.add_argument("--dataset-id", required=True, help="expected default Dataset ID; must match the Run")
    parser.add_argument("--actor-id", required=True, help="expected actId/actorId value; must match the Run")
    parser.add_argument("--output", type=Path, help="write sanitized summary JSON (use a Git-ignored path)")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
