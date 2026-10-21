"""Safe CLI for one explicit Instagram URL or an existing journalled Run."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from reliable_actor import (APPROVED_BUILD_NUMBER, EXIT_CODES, RestTransport, RunJournal,
    build_run_input, execute_input, load_resume_record, sanitize, write_private)

DEFAULT_ACTOR_ID = "apple_yang/instagram-transcripts-scraper"
ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "sample-output" / "generated"
OUTPUT_FILE = OUTPUT_DIR / "python-single-url-response.json"
JOURNAL = RunJournal(OUTPUT_DIR / "python-run-journal.jsonl")
DATASET_PAGE_LIMIT = 100
_BARE_INSTAGRAM_URL = re.compile(r"^https://(?:www\.)?instagram\.com/(?:reel|reels|p)/[A-Za-z0-9_-]+/?$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch the transcript for one explicitly supplied Instagram Reel URL.")
    parser.add_argument("url", nargs="?", help="bare Instagram Reel URL; required unless --resume is used")
    parser.add_argument("--resume", metavar="RUN_ID", help="resume only an existing Run recorded in the local journal")
    return parser


def validate_url(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or not _BARE_INSTAGRAM_URL.fullmatch(value):
        raise ValueError("Pass a bare HTTPS Instagram Reel URL (not a Markdown link or URL with extra text).")
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"instagram.com", "www.instagram.com"} or parsed.query or parsed.fragment:
        raise ValueError("Pass a bare HTTPS Instagram Reel URL without query parameters or fragments.")
    return value


def prepare_cli_request(argv: list[str], environ: dict[str, str]) -> dict:
    """Pure argument/config validation seam; it never loads .env or performs I/O."""
    args = build_parser().parse_args(argv)
    if args.resume and args.url:
        build_parser().error("provide either a URL or --resume RUN_ID, not both")
    if not args.resume and not args.url:
        build_parser().error("an explicit Instagram URL is required (or use --resume RUN_ID)")
    try:
        url = validate_url(args.url) if args.url else None
    except ValueError as exc:
        build_parser().error(str(exc))
    token = environ.get("APIFY_TOKEN")
    if not token:
        raise RuntimeError("APIFY_TOKEN is missing. Set it in the process environment or repository .env file.")
    return {"args": args, "url": url, "token": token}


def format_output(result: dict) -> dict:
    """Return a stable, credential-sanitised JSON object for both success and failure."""
    raw_items = sanitize(result.get("rawItems", []))
    raw_items = raw_items if isinstance(raw_items, list) else []
    transcript_item = next((item for item in raw_items if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip()), {})
    text = transcript_item.get("text")
    segments = transcript_item.get("segments")
    segments = segments if isinstance(segments, list) else []
    return {
        "rowId": result.get("rowId"),
        "sourceUrl": result.get("sourceUrl"),
        "runId": result.get("runId"),
        "datasetId": result.get("datasetId"),
        "status": result.get("status", "unknown"),
        "error": result.get("error") or "",
        "transcript": text if isinstance(text, str) else None,
        "segments": segments,
        "segmentsCount": len(segments),
        "itemCount": len(raw_items),
        "datasetComplete": result.get("datasetComplete"),
        "datasetLimit": result.get("datasetLimit"),
        "buildNumber": result.get("buildNumber"),
        "buildId": result.get("buildId"),
        "buildVerification": result.get("buildVerification"),
        "items": raw_items,
    }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.resume and args.url:
        parser.error("provide either a URL or --resume RUN_ID, not both")
    if not args.resume and not args.url:
        parser.error("an explicit Instagram URL is required (or use --resume RUN_ID)")
    if args.url:
        try:
            validate_url(args.url)
        except ValueError as exc:
            parser.error(str(exc))

    # Loading .env is only for credentials/configuration; URL input is always explicit.
    load_dotenv(ROOT / ".env")
    token = os.getenv("APIFY_TOKEN")
    if not token:
        print("Error: APIFY_TOKEN is missing. Set it in the process environment or repository .env file.", file=sys.stderr)
        return 2
    actor_id = os.getenv("APIFY_ACTOR_ID", DEFAULT_ACTOR_ID)
    try:
        previous = load_resume_record(JOURNAL, args.resume, actor_id) if args.resume else None
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    source_url = previous["sourceUrl"] if previous else args.url
    try:
        result = execute_input(
            transport=RestTransport(token), actor_id=actor_id,
            run_input=build_run_input(source_url, os.getenv("INSTAGRAM_SESSIONID")),
            source_url=source_url, journal=JOURNAL,
            max_total_charge_usd=os.getenv("APIFY_MAX_TOTAL_CHARGE_USD"),
            require_charge_cap=os.getenv("APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD") == "1",
            build=os.getenv("APIFY_BUILD", APPROVED_BUILD_NUMBER), require_build=True,
            dataset_limit=DATASET_PAGE_LIMIT,
            run_id=args.resume, dataset_id=(previous or {}).get("datasetId"), row_id=(previous or {}).get("rowId"),
        )
    except Exception as exc:
        # Keep unexpected local errors readable and avoid dumping transport internals.
        result = {"status": "transport_error", "sourceUrl": source_url, "error": f"Local execution failed: {type(exc).__name__}"}
    output = format_output(result)
    try:
        write_private(OUTPUT_FILE, json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"Warning: could not save output file ({type(exc).__name__}); the result is still printed below.", file=sys.stderr)
    print(json.dumps(output, ensure_ascii=False))
    return EXIT_CODES.get(output["status"], 7)


if __name__ == "__main__":
    raise SystemExit(main())
