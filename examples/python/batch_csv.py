"""Run one independently billed Actor Run for each explicitly supplied CSV row.

This is the CSV Batch mode. It is separate from Native Bulk (one run with ``bulkUrls``).
Importing this module does not read credentials, load dotenv, create files, or access network.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

if __package__:
    from . import client as api_client
    from .reliable_actor import RunJournal, safe_error, sanitize, validate_build, validate_run_charge_cap
else:
    import client as api_client
    from reliable_actor import RunJournal, safe_error, sanitize, validate_build, validate_run_charge_cap

DEFAULT_ACTOR_ID = "apple_yang/instagram-transcripts-scraper"
DEFAULT_CONCURRENCY = 3


class CsvInputError(ValueError):
    """The CSV cannot safely be submitted as a batch."""


class _LockedJournal:
    """Serialize journal appends made by concurrent row workers."""

    def __init__(self, journal: RunJournal):
        self._journal = journal
        self._lock = threading.Lock()

    def append(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._journal.append(record)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one independent Actor Run per Reel URL in a CSV file."
    )
    parser.add_argument("csv_file", help="CSV path with a videoUrl column")
    parser.add_argument(
        "--concurrency",
        help=f"maximum simultaneous Runs (default: MAX_CONCURRENCY or {DEFAULT_CONCURRENCY})",
    )
    parser.add_argument(
        "--output",
        help="JSON result path; relative paths use the current directory; existing files are never overwritten",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate the CSV and print the Run plan without reading credentials or creating Runs",
    )
    return parser


def parse_concurrency(cli_value: str | None, environment: Mapping[str, str]) -> int:
    raw_value = cli_value if cli_value is not None else environment.get("MAX_CONCURRENCY", str(DEFAULT_CONCURRENCY))
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        raise CsvInputError("concurrency must be a positive whole number (for example, 3)") from None
    if value < 1:
        raise CsvInputError("concurrency must be at least 1")
    return value


def read_urls(file: Path) -> list[dict[str, str]]:
    """Read and validate all non-empty videoUrl records before any Run is submitted."""
    try:
        with file.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or "videoUrl" not in reader.fieldnames:
                raise CsvInputError("CSV line 1: missing required videoUrl column in the header")
            rows: list[dict[str, str]] = []
            for row in reader:
                row_number = reader.line_num
                if None in row:
                    raise CsvInputError(f"CSV row ending at line {row_number} has more values than its header")
                value = row.get("videoUrl")
                if value is None:
                    raise CsvInputError(f"CSV line {row_number}: missing videoUrl field")
                if not value.strip():
                    # Keep the established behavior for blank URL rows: they are not tasks.
                    continue
                source_url = value.strip()
                try:
                    api_client._validate_url(source_url)
                except api_client.ConfigurationError as exc:
                    raise CsvInputError(f"CSV line {row_number}: invalid videoUrl: {exc}") from None
                rows.append({"inputRow": str(row_number), "sourceUrl": source_url})
    except UnicodeDecodeError as exc:
        raise CsvInputError(f"CSV is not valid UTF-8: {exc}") from None
    except csv.Error as exc:
        raise CsvInputError(f"Could not parse CSV: {exc}") from None
    if not rows:
        raise CsvInputError("CSV contains no non-empty videoUrl rows")
    return rows


def _reserve_output_path(requested: str | None, output_dir: Path) -> Path:
    """Create an exclusive placeholder so a result can never truncate an old artifact."""
    def create_exclusive(target: Path) -> None:
        file_mode = 0o600 if os.name == "posix" else 0o666
        descriptor = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, file_mode)
        os.close(descriptor)

    if requested:
        target = Path(requested).expanduser()
        if not target.is_absolute():
            target = Path.cwd() / target
        target = target.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            create_exclusive(target)
        except FileExistsError:
            raise CsvInputError(f"Output file already exists; choose another path: {target}") from None
        return target

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = output_dir / f"python-batch-results-{timestamp}.json"
    candidate = base
    suffix = 1
    while True:
        try:
            create_exclusive(candidate)
            return candidate
        except FileExistsError:
            candidate = base.with_name(f"{base.stem}-{suffix}{base.suffix}")
            suffix += 1


def _result_row(row: Mapping[str, str], result: Any = None, error: Exception | None = None) -> dict[str, Any]:
    if error is not None:
        if isinstance(error, api_client.CreationUnknownError):
            status = "creation_unknown"
        elif isinstance(error, (api_client.TranscriptTransportError, api_client.ProtocolError, api_client.ConfigurationError)):
            status = "transport_error"
        else:
            status = "unknown"
        return {
            "inputRow": row["inputRow"],
            "sourceUrl": row["sourceUrl"],
            "status": status,
            "runId": getattr(error, "run_id", None),
            "datasetId": getattr(error, "dataset_id", None),
            "transcript": None,
            "segments": [],
            "segmentsCount": 0,
            "items": [],
            "datasetComplete": None,
            "error": safe_error(error),
        }

    if is_dataclass(result):
        result = asdict(result)
    if not isinstance(result, dict):
        return {
            "inputRow": row["inputRow"], "sourceUrl": row["sourceUrl"], "status": "unknown",
            "runId": None, "datasetId": None, "transcript": None, "segments": [],
            "segmentsCount": 0, "items": [], "datasetComplete": None,
            "error": "Transcript client returned an unsupported result shape",
        }
    segments = result.get("segments") if isinstance(result.get("segments"), list) else []
    items = result.get("items") if isinstance(result.get("items"), list) else []
    return {
        "inputRow": row["inputRow"],
        "sourceUrl": row["sourceUrl"],
        "status": result.get("status", "unknown"),
        "runId": result.get("run_id", result.get("runId")),
        "datasetId": result.get("dataset_id", result.get("datasetId")),
        "transcript": result.get("text", result.get("transcript")),
        "segments": segments,
        "segmentsCount": len(segments),
        "items": items,
        "datasetComplete": result.get("dataset_complete", result.get("datasetComplete")),
        "error": result.get("error"),
    }


def _write_result(path: Path, document: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(sanitize(document), stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    transcript_runner: Callable[..., Any] | None = None,
    output_dir: Path | None = None,
    journal: Any = None,
    stdout: Any = None,
    stderr: Any = None,
) -> int:
    """CLI orchestration with dependency seams; tests inject a fully offline transcript runner."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    try:
        args = build_parser().parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code or 0)

    env = environment if environment is not None else os.environ
    try:
        concurrency = parse_concurrency(args.concurrency, env)
        csv_path = Path(args.csv_file).expanduser()
        if not csv_path.is_absolute():
            csv_path = Path.cwd() / csv_path
        rows = read_urls(csv_path)
    except (CsvInputError, OSError) as exc:
        print(f"Error: {exc}", file=err)
        return 2

    if args.dry_run:
        print(json.dumps({
            "mode": "csv_batch_independent_runs",
            "rows": len(rows),
            "concurrency": concurrency,
            "maximumActorRuns": len(rows),
            "source": str(csv_path.resolve()),
        }, ensure_ascii=False, sort_keys=True), file=out)
        return 0

    token = env.get("APIFY_TOKEN")
    if not isinstance(token, str) or not token.strip():
        print("Error: APIFY_TOKEN is required in the process environment. No Actor Run was created.", file=err)
        return 2

    actor_id = env.get("APIFY_ACTOR_ID", DEFAULT_ACTOR_ID)
    build = env.get("APIFY_BUILD", api_client.APPROVED_BUILD_NUMBER)
    cap = env.get("APIFY_MAX_TOTAL_CHARGE_USD")
    require_cap = env.get("APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD") == "1"
    try:
        if not isinstance(actor_id, str) or not actor_id.strip() or actor_id.strip().startswith("/"):
            raise CsvInputError("APIFY_ACTOR_ID must be a non-empty Actor ID or owner/name")
        validate_build(build, required=True)
        validate_run_charge_cap(cap, required=require_cap)
        selected_output_dir = Path(output_dir) if output_dir is not None else csv_path.parent
        output_path = _reserve_output_path(args.output, Path(selected_output_dir))
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=err)
        return 2

    active_journal = journal if journal is not None else _LockedJournal(RunJournal(output_path.parent / "python-run-journal.jsonl"))
    runner = transcript_runner if transcript_runner is not None else api_client.get_transcript
    results: list[dict[str, Any] | None] = [None] * len(rows)

    def submit(index: int, row: dict[str, str]) -> dict[str, Any]:
        try:
            result = runner(
                row["sourceUrl"], token=token, actor_id=actor_id, build=build,
                max_total_charge_usd=cap, require_charge_cap=require_cap,
                journal=active_journal,
            )
            return _result_row(row, result=result)
        except Exception as exc:  # Keep independent row outcomes even when one call fails.
            return _result_row(row, error=exc)

    print(
        f"Submitting {len(rows)} independent Actor Run(s) (maximum {len(rows)} total), concurrency={concurrency}.",
        file=out,
    )
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(submit, index, row): index for index, row in enumerate(rows)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:  # Defensive: each worker normally converts its own failures.
                results[index] = _result_row(rows[index], error=exc)

    complete_rows = [row for row in results if row is not None]
    counts: dict[str, int] = {}
    for row in complete_rows:
        status = row["status"]
        counts[status] = counts.get(status, 0) + 1
    document = {
        "schemaVersion": 1,
        "mode": "csv_batch_independent_runs",
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "status": "success" if len(complete_rows) == len(rows) and all(row["status"] == "success" for row in complete_rows) else "partial_failure",
        "processed": len(complete_rows),
        "requested": len(rows),
        "concurrency": concurrency,
        "counts": counts,
        "rows": complete_rows,
    }
    try:
        _write_result(output_path, document)
    except OSError as exc:
        print(f"Error: results could not be written to {output_path}: {exc}", file=err)
        print("Run IDs remain in the append-only journal when journal writes succeeded.", file=err)
        return 2

    print(json.dumps({"status": document["status"], "processed": len(complete_rows), "counts": counts, "output": str(output_path)}, ensure_ascii=False, sort_keys=True), file=out)
    return 0 if document["status"] == "success" else 1


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
