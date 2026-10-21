"""Small staged Apify REST runner. Safe to import: no env loading or network at import time."""
from __future__ import annotations

import json
import email.utils
import math
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TERMINAL = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}
STATUSES = ("success", "actor_error", "empty", "no_transcript", "unknown", "transport_error", "run_failed", "creation_unknown")
EXIT_CODES = {"success": 0, "actor_error": 4, "empty": 5, "no_transcript": 6, "unknown": 7, "transport_error": 8, "run_failed": 9, "creation_unknown": 10}
APPROVED_BUILD_NUMBER = "0.0.50"
APPROVED_BUILD_ID = "aJLRmMdQapLQRT4sJ"


def build_run_input(video_url: str, sessionid: str | None = None) -> dict[str, str]:
    """Build a conservative Reel input; omit an unset optional sessionid."""
    result = {"videoUrl": video_url}
    if sessionid:
        result["sessionid"] = sessionid
    return result


def validate_run_charge_cap(value, *, required: bool = False) -> float | None:
    """Validate an optional positive USD cap before creating a Run."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError("APIFY_MAX_TOTAL_CHARGE_USD is required for capped test mode")
        return None
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError("APIFY_MAX_TOTAL_CHARGE_USD must be a finite positive number") from None
    if not amount.is_finite() or amount <= 0:
        raise ValueError("APIFY_MAX_TOTAL_CHARGE_USD must be a finite positive number")
    return float(amount)


def validate_build(value, *, required: bool = False) -> str | None:
    """Validate an explicit Apify Build number without treating it as Actor input."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError("APIFY_BUILD is required when APIFY_REQUIRE_BUILD=1")
        return None
    build = str(value).strip()
    if not re.fullmatch(r"\d+(?:\.\d+){0,2}", build) or build.lower() == "latest":
        raise ValueError("APIFY_BUILD must be an explicit numeric Build number")
    if required and build != APPROVED_BUILD_NUMBER:
        raise ValueError(f"APIFY_BUILD must be {APPROVED_BUILD_NUMBER} in controlled test mode")
    return build


@dataclass
class ApiError(Exception):
    message: str
    status: int | None = None
    retry_after: float | None = None
    ambiguous: bool = False

    def __str__(self):
        return self.message


class RestTransport:
    """Minimal injectable transport. No retries; caller controls stages."""
    def __init__(self, token: str, opener=None, base_url="https://api.apify.com/v2"):
        self.token = token
        self.opener = opener or urllib.request.urlopen
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, body=None, timeout=30, query=None):
        if query:
            from urllib.parse import urlencode
            path += ("&" if "?" in path else "?") + urlencode(query)
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=data, method=method.upper(), headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with self.opener(request, timeout=timeout) as response:
                raw = response.read()
                try: return json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    raise ApiError("Apify returned invalid JSON", ambiguous=method.upper() == "POST") from None
        except urllib.error.HTTPError as exc:
            retry = exc.headers.get("Retry-After") if exc.headers else None
            try:
                retry = float(retry) if retry is not None else None
                if retry is not None and (not math.isfinite(retry) or retry < 0): retry = None
            except ValueError:
                try: retry = max(0, (email.utils.parsedate_to_datetime(retry).timestamp() - time.time())) if retry else None
                except (TypeError, ValueError, OverflowError): retry = None
            raise ApiError(f"Apify HTTP {exc.code}", exc.code, retry, ambiguous=method.upper() == "POST" and exc.code >= 500) from None
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            raise ApiError(f"Apify {method.upper()} transport failure: {type(exc).__name__}", ambiguous=method.upper() == "POST") from None


def safe_error(error: Exception) -> str:
    # Never persist headers, tokens, session IDs, or arbitrary upstream response bodies.
    return _redact_text(str(error).replace("\n", " "))[:300]


def write_private(path: Path, text: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try: path.chmod(0o600)
        except FileNotFoundError: pass
    file_mode = 0o600 if os.name == "posix" else 0o666
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, file_mode)
    set_fd_mode = getattr(os, "fchmod", None)
    if os.name == "posix" and callable(set_fd_mode):
        set_fd_mode(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def _redact_text(value: str) -> str:
    value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*", r"\1[REDACTED]", value)
    return re.sub(r"(?i)(sessionid|token|authorization|cookie|password|api[_-]?key)(\s*[:=]\s*[\"']?)[^\s,;&\"']+", r"\1\2[REDACTED]", value)


class RunJournal:
    def __init__(self, path: Path): self.path = Path(path)
    def validate(self):
        if not self.path.exists(): return
        with self.path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                try: row = json.loads(line)
                except json.JSONDecodeError as exc: raise ValueError(f"Run journal is corrupt at line {line_number}; refusing to continue") from exc
                if not isinstance(row, dict): raise ValueError(f"Run journal record at line {line_number} is not an object; refusing to continue")
    def append(self, record: dict):
        self.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        file_mode = 0o600 if os.name == "posix" else 0o666
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, file_mode)
        set_fd_mode = getattr(os, "fchmod", None)
        if os.name == "posix" and callable(set_fd_mode):
            set_fd_mode(descriptor, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
    def latest(self, run_id: str):
        if not self.path.exists(): return None
        found = None
        with self.path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                try: row = json.loads(line)
                except json.JSONDecodeError as exc: raise ValueError(f"Run journal is corrupt at line {line_number}; refusing resume") from exc
                if not isinstance(row, dict): raise ValueError(f"Run journal record at line {line_number} is not an object; refusing resume")
                if row.get("runId") == run_id: found = row
        return found


def load_resume_record(journal: RunJournal, run_id: str, actor_id: str):
    record = journal.latest(run_id)
    if record is None: raise ValueError(f"No journal record found for Run ID {run_id}; refusing resume")
    if record.get("runId") != run_id or record.get("actorId") != actor_id:
        raise ValueError("Run journal Actor/Run ID does not match the requested resume; refusing resume")
    if not isinstance(record.get("sourceUrl"), str) or not record["sourceUrl"].strip() or not isinstance(record.get("rowId"), str):
        raise ValueError("Run journal is missing input association fields; refusing resume")
    return record


def classify_items(items: Any) -> tuple[str, str]:
    if not isinstance(items, list): return "unknown", "Dataset response is not an item list"
    if not items: return "empty", "Dataset contains no items"
    if not all(isinstance(item, dict) for item in items): return "unknown", "Dataset contains a non-object item"
    errors = [str(item.get("errMsg")).strip() for item in items if item.get("errMsg") is not None and str(item.get("errMsg")).strip()]
    texts = [item.get("text") for item in items]
    if errors:
        return "actor_error", _redact_text("; ".join(errors))[:500]
    if any(isinstance(text, str) and text.strip() for text in texts): return "success", ""
    if any("text" in item and item.get("text") is None for item in items): return "no_transcript", "Transcript text is null"
    if any("text" not in item for item in items): return "no_transcript", "Transcript text is absent"
    if any(isinstance(text, str) and not text.strip() for text in texts): return "no_transcript", "Transcript text is empty"
    return "unknown", "Transcript text has an unsupported type"


def _deadline(deadline):
    if time.monotonic() >= deadline: raise ApiError("Overall run deadline exceeded")


def _retry_get(transport, path, *, deadline, max_attempts=4, sleep=time.sleep, clock=time.monotonic):
    last = None
    for attempt in range(max_attempts):
        _deadline(deadline)
        try: return transport.request("GET", path, timeout=max(1, min(30, deadline - clock())))
        except ApiError as exc:
            last = exc
            retryable = exc.status == 429 or (exc.status is not None and 500 <= exc.status < 600) or exc.status is None
            if not retryable or attempt + 1 >= max_attempts: raise
            delay = exc.retry_after if exc.retry_after is not None else min(2 ** attempt, 8)
            if clock() + delay >= deadline: raise
            sleep(delay)
    raise last


def execute_input(*, transport, actor_id, run_input, source_url, journal, deadline_seconds=900, max_attempts=4, sleep=time.sleep, clock=time.monotonic, run_id=None, dataset_id=None, row_id=None, max_total_charge_usd=None, require_charge_cap=False, build=None, require_build=False, dataset_limit=None):
    deadline = clock() + deadline_seconds
    row_id = row_id or str(uuid.uuid4())
    record = {"rowId": row_id, "sourceUrl": source_url, "actorId": actor_id, "runId": run_id, "datasetId": dataset_id, "stage": "start", "status": "unknown", "updatedAt": datetime.now(timezone.utc).isoformat()}
    def save(stage, status="unknown", error=None):
        record.update(stage=stage, status=status, updatedAt=datetime.now(timezone.utc).isoformat())
        if error: record["error"] = safe_error(error)
        else: record.pop("error", None)
        journal.append(record.copy())
    try:
        charge_cap = validate_run_charge_cap(max_total_charge_usd, required=require_charge_cap) if run_id is None else None
        selected_build = validate_build(build, required=require_build)
    except ValueError as exc:
        return {"rowId": row_id, "sourceUrl": source_url, "status": "transport_error", "runId": run_id, "error": str(exc)}
    if dataset_limit is not None and (isinstance(dataset_limit, bool) or not isinstance(dataset_limit, int) or dataset_limit <= 0):
        return {"rowId": row_id, "sourceUrl": source_url, "status": "transport_error", "runId": run_id,
            "error": "Dataset page limit must be a positive integer"}
    if run_id is None:
        try: save("creating")
        except (OSError, ValueError) as exc:
            return {"rowId": row_id, "sourceUrl": source_url, "status": "transport_error", "runId": None, "error": safe_error(exc)}
        actor_path = "/acts/" + actor_id.replace("/", "~") + "/runs"
        if clock() >= deadline:
            save("create_failed", "transport_error", "Overall run deadline exceeded before POST")
            return {"rowId": row_id, "sourceUrl": source_url, "status": "transport_error", "runId": None, "error": "Overall run deadline exceeded before POST"}
        try:
            run_options = {"restartOnError": "false"} if charge_cap is not None or selected_build is not None else {}
            if charge_cap is not None:
                run_options["maxTotalChargeUsd"] = charge_cap
            if selected_build is not None:
                run_options["build"] = selected_build
            created = transport.request("POST", actor_path, run_input, timeout=max(1, min(30, deadline-clock())), query=run_options or None)
        except ApiError as exc:
            # The Actor/platform's 429 creation semantics are unverified. Do not risk a second paid POST.
            if exc.status == 429:
                state = "creation_unknown"
                exc = ApiError("HTTP 429 on Run creation; acceptance semantics are unverified; POST was not retried", 429)
            else:
                state = "creation_unknown" if exc.ambiguous or exc.status is None else "transport_error"
            save("creation_unknown" if state == "creation_unknown" else "create_failed", state, exc)
            return {"rowId": row_id, "sourceUrl": source_url, "status": state, "error": safe_error(exc), "runId": None}
        created = created.get("data", created) if isinstance(created, dict) else None
        run_id = created.get("id") if isinstance(created, dict) else None
        dataset_id = created.get("defaultDatasetId") if isinstance(created, dict) else None
        if not run_id:
            save("creation_unknown", "creation_unknown", "POST response did not include a run ID")
            return {"rowId": row_id, "sourceUrl": source_url, "status": "creation_unknown", "runId": None, "error": "POST response did not include a run ID"}
        record.update(runId=run_id, datasetId=dataset_id)
        save("run_created")
        if selected_build is not None:
            build_number = created.get("buildNumber") if isinstance(created, dict) else None
            build_id = created.get("buildId") if isinstance(created, dict) else None
            verification = "response"
            if not build_number or not build_id:
                try:
                    verified_run = _retry_get(transport, "/actor-runs/" + run_id, deadline=deadline, max_attempts=max_attempts, sleep=sleep, clock=clock)
                    verified_run = verified_run.get("data", verified_run)
                    build_number = build_number or verified_run.get("buildNumber")
                    build_id = build_id or verified_run.get("buildId")
                    verification = "run_get"
                except ApiError as exc:
                    record.update(buildNumber=build_number, buildId=build_id, buildVerification="failed")
                    save("build_mismatch", "transport_error", f"Could not verify actual Build identity: {safe_error(exc)}")
                    return {"rowId": row_id, "sourceUrl": source_url, "runId": run_id, "datasetId": dataset_id,
                        "status": "transport_error", "error": "Could not verify actual Build identity", "stage": "build_mismatch",
                        "buildNumber": build_number, "buildId": build_id, "buildVerification": "failed"}
            if not build_number or not build_id or str(build_number) != selected_build or (selected_build == APPROVED_BUILD_NUMBER and build_id != APPROVED_BUILD_ID):
                record.update(buildNumber=build_number, buildId=build_id, buildVerification="mismatch" if build_number or build_id else "missing")
                save("build_mismatch", "transport_error", "Actual Build identity is missing or does not match the requested Build")
                return {"rowId": row_id, "sourceUrl": source_url, "runId": run_id, "datasetId": dataset_id,
                    "status": "transport_error", "error": "Actual Build identity is missing or does not match the requested Build",
                    "stage": "build_mismatch", "buildNumber": build_number, "buildId": build_id,
                    "buildVerification": record["buildVerification"]}
            record.update(buildNumber=str(build_number), buildId=build_id, buildVerification=verification)
            save("build_verified")
    else:
        record.update(runId=run_id, datasetId=dataset_id)
        save("resuming")
    try:
        while True:
            _deadline(deadline)
            run = _retry_get(transport, "/actor-runs/" + run_id, deadline=deadline, max_attempts=max_attempts, sleep=sleep, clock=clock)
            run = run.get("data", run)
            if selected_build is not None and run_id is not None and record.get("buildVerification") is None:
                build_number, build_id = run.get("buildNumber"), run.get("buildId")
                if str(build_number) != selected_build or not build_id or (selected_build == APPROVED_BUILD_NUMBER and build_id != APPROVED_BUILD_ID):
                    record.update(buildNumber=build_number, buildId=build_id, buildVerification="mismatch" if build_number or build_id else "missing")
                    save("build_mismatch", "transport_error", "Run Build identity is missing or does not match the requested Build")
                    return {"rowId": row_id, "sourceUrl": source_url, "runId": run_id, "datasetId": dataset_id,
                        "status": "transport_error", "error": "Run Build identity is missing or does not match the requested Build",
                        "stage": "build_mismatch", "buildNumber": build_number, "buildId": build_id,
                        "buildVerification": record["buildVerification"]}
                record.update(buildNumber=str(build_number), buildId=build_id, buildVerification="run_get")
                save("build_verified")
            status = run.get("status")
            if status in TERMINAL:
                if status != "SUCCEEDED":
                    save("run_finished", "run_failed", f"Run ended with {status}")
                    return {"rowId": row_id, "sourceUrl": source_url, "runId": run_id, "datasetId": dataset_id, "status": "run_failed", "error": f"Run ended with {status}"}
                run_dataset_id = run.get("defaultDatasetId")
                if dataset_id and run_dataset_id and dataset_id != run_dataset_id:
                    raise ApiError("Journal Dataset ID does not match the Run response")
                dataset_id = dataset_id or run_dataset_id
                record["datasetId"] = dataset_id
                save("run_finished")
                break
            sleep(min(2, max(0, deadline-clock())))
        if not dataset_id:
            save("recoverable", "transport_error", "Run succeeded without a dataset ID")
            return {"rowId": row_id, "sourceUrl": source_url, "runId": run_id, "status": "transport_error", "error": "Run succeeded without a dataset ID"}
        dataset_path = "/datasets/" + dataset_id + "/items"
        if dataset_limit is not None:
            dataset_path += f"?limit={int(dataset_limit)}&offset=0"
        items = _retry_get(transport, dataset_path, deadline=deadline, max_attempts=max_attempts, sleep=sleep, clock=clock)
        # Dataset visibility can lag terminal Run status; confirm empty reads on the same Dataset.
        for empty_attempt in range(2):
            if items != [] or clock() + (empty_attempt + 1) >= deadline: break
            sleep(empty_attempt + 1)
            items = _retry_get(transport, dataset_path, deadline=deadline, max_attempts=max_attempts, sleep=sleep, clock=clock)
        dataset_complete = not (dataset_limit is not None and isinstance(items, list) and len(items) >= dataset_limit)
        state, message = classify_items(items)
        if not dataset_complete:
            state, message = "unknown", f"Dataset reached the {dataset_limit}-item page limit; completeness is unverified"
        save("complete", state, message or None)
        return {"rowId": row_id, "sourceUrl": source_url, "runId": run_id, "datasetId": dataset_id, "status": state, "error": message,
            "rawItems": items, "datasetLimit": dataset_limit, "datasetComplete": dataset_complete,
            "buildNumber": record.get("buildNumber"), "buildId": record.get("buildId"), "buildVerification": record.get("buildVerification")}
    except ApiError as exc:
        state = "transport_error"
        save("recoverable", state, exc)
        return {"rowId": row_id, "sourceUrl": source_url, "runId": run_id, "datasetId": dataset_id, "status": state, "error": safe_error(exc)}


def summarize(results):
    counts = {key: 0 for key in STATUSES}
    for result in results:
        status = result.get("status", "unknown")
        counts[status if status in counts else "unknown"] += 1
    counts["processed"] = sum(counts.values())
    counts["failed"] = counts["processed"] - counts["success"]
    return counts


def sanitize(value):
    """Drop credential-like fields recursively before persisting raw result data."""
    blocked = {"token", "sessionid", "cookie", "authorization", "password", "secret", "accesstoken", "refreshtoken", "apikey"}
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items() if k.lower().replace("_", "").replace("-", "") not in blocked}
    if isinstance(value, list): return [sanitize(v) for v in value]
    if isinstance(value, str): return _redact_text(value)
    return value
