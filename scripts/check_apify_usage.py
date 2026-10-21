#!/usr/bin/env python3
"""Read-only Apify monthly Usage check. Never starts an Actor Run."""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
USAGE_URL = "https://api.apify.com/v2/users/me/usage/monthly"
REQUEST_TIMEOUT_SECONDS = 20
SENSITIVE_KEY_PARTS = (
    "token", "authorization", "cookie", "password", "secret", "email",
    "username", "apikey", "accesskey", "session",
)


class UsageCheckError(Exception):
    """A safe-to-display error; never contains an API response body or headers."""


def _safe_key(key: Any) -> str:
    value = str(key)
    lowered = re.sub(r"[^a-z0-9]", "", value.lower())
    if any(part in lowered for part in SENSITIVE_KEY_PARTS):
        return "[redacted-key]"
    return value[:120]


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _walk_unknown(value: Any, path: str, out: list[dict[str, str]]) -> None:
    """Record unknown field paths/types only; never serialize their values."""
    if isinstance(value, dict):
        if not value:
            out.append({"path": path, "type": "object", "meaning": "unknown"})
        for key, child in value.items():
            safe = _safe_key(key)
            child_path = f"{path}.{safe}" if path else safe
            _walk_unknown(child, child_path, out)
    elif isinstance(value, list):
        out.append({"path": path, "type": "array", "meaning": "unknown; values omitted"})
    else:
        out.append({"path": path, "type": _type_name(value), "meaning": "unknown; value omitted"})


def summarize_usage(data: dict[str, Any], *, queried_at: datetime | None = None) -> dict[str, Any]:
    """Keep only billing-cycle dates and numeric API values under monthlyServiceUsage.

    Service metric units and billing meaning are deliberately not inferred. Other
    fields are represented only by path and JSON type; balances/credits are not
    calculated or reported as available funds.
    """
    queried_at = queried_at or datetime.now(timezone.utc)
    if queried_at.tzinfo is None:
        queried_at = queried_at.replace(tzinfo=timezone.utc)

    cycle = data.get("usageCycle")
    safe_cycle: dict[str, str] | None = None
    unknown: list[dict[str, str]] = []
    if isinstance(cycle, dict):
        safe_cycle = {}
        for key in ("startAt", "endAt"):
            value = cycle.get(key)
            if isinstance(value, str):
                safe_cycle[key] = value[:80]
            elif key in cycle:
                unknown.append({"path": f"usageCycle.{key}", "type": _type_name(value), "meaning": "unknown; value omitted"})
        for key, value in cycle.items():
            if key not in ("startAt", "endAt"):
                unknown.append({"path": "usageCycle." + _safe_key(key), "type": _type_name(value), "meaning": "unknown; value omitted"})
        if not safe_cycle:
            safe_cycle = None
    elif cycle is not None:
        unknown.append({"path": "usageCycle", "type": _type_name(cycle), "meaning": "unknown; value omitted"})

    monthly_service_usage = data.get("monthlyServiceUsage")
    service_metrics: list[dict[str, Any]] = []

    def collect_metrics(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                collect_metrics(child, f"{path}.{_safe_key(key)}")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            service_metrics.append({
                "field": path,
                "reportedValue": value,
                "unit": "unknown",
                "billingMeaning": "API-reported monthly service Usage metric; cost or balance not inferred",
            })
        else:
            _walk_unknown(value, path, unknown)

    if isinstance(monthly_service_usage, dict):
        collect_metrics(monthly_service_usage, "monthlyServiceUsage")
    elif "monthlyServiceUsage" in data:
        _walk_unknown(monthly_service_usage, "monthlyServiceUsage", unknown)

    for key, value in data.items():
        if key not in ("usageCycle", "monthlyServiceUsage"):
            _walk_unknown(value, _safe_key(key), unknown)

    return {
        "queriedAt": queried_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "endpoint": "GET /v2/users/me/usage/monthly",
        "usageCycle": safe_cycle,
        "monthlyServiceUsage": service_metrics,
        "unknownFields": unknown,
        "balance": "unknown; this script does not infer or calculate available balance",
        "credits": "unknown unless explicitly represented by a documented Usage metric; no credit balance is inferred",
    }


def fetch_usage(token: str, *, opener: Callable[..., Any] | None = None) -> dict[str, Any]:
    if not token or not token.strip():
        raise UsageCheckError("APIFY_TOKEN is missing; no request was sent")
    request = urllib.request.Request(
        USAGE_URL,
        headers={"Authorization": "Bearer " + token.strip(), "Accept": "application/json"},
        method="GET",
    )
    open_request = opener or urllib.request.urlopen
    try:
        with open_request(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read()
            status = getattr(response, "status", 200)
            if status < 200 or status >= 300:
                raise UsageCheckError(f"Apify Usage request returned HTTP {status}")
    except urllib.error.HTTPError as exc:
        raise UsageCheckError(f"Apify Usage request returned HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        reason_type = type(exc.reason).__name__
        raise UsageCheckError(f"Apify Usage network request failed ({reason_type})") from None
    except (TimeoutError, OSError) as exc:
        raise UsageCheckError(f"Apify Usage network request failed ({type(exc).__name__})") from None

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise UsageCheckError("Apify Usage response was not valid UTF-8 JSON") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise UsageCheckError("Apify Usage response had an unexpected JSON structure")
    return summarize_usage(payload["data"])


def _ensure_git_safe_output(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    try:
        resolved.relative_to(ROOT)
    except ValueError:
        return resolved  # Outside this repository cannot be committed to it.

    relative = os.path.relpath(resolved, ROOT)
    try:
        check = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", "--", relative],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        raise UsageCheckError("Cannot verify that --output is Git-ignored; refusing to write") from None
    if check.returncode != 0:
        raise UsageCheckError("--output is inside the repository but is not Git-ignored; refusing to write")
    return resolved


def write_private_json(path: Path, result: dict[str, Any]) -> None:
    path = _ensure_git_safe_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise UsageCheckError(f"Cannot safely write --output ({type(exc).__name__})") from None
    set_fd_mode = getattr(os, "fchmod", None)
    if os.name == "posix" and callable(set_fd_mode):
        set_fd_mode(descriptor, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read Apify monthly Usage (GET only; never starts an Actor).")
    parser.add_argument("--output", type=Path, help="write the sanitized JSON report to this file (must be Git-ignored if inside the repository)")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        print("Error: python-dotenv is required to load the repository .env file", file=sys.stderr)
        return 2

    token = os.getenv("APIFY_TOKEN")
    try:
        result = fetch_usage(token or "")
        serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            write_private_json(args.output, result)
        sys.stdout.write(serialized)
        return 0
    except UsageCheckError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
