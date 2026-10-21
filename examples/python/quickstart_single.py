"""Tiny user-facing example. Use APIFY_TOKEN in the process environment; no .env URL lookup."""
from __future__ import annotations

import argparse
import json
import sys

try:
    from .client import ConfigurationError, CreationUnknownError, ProtocolError, TranscriptTransportError, get_transcript
except ImportError:
    from client import ConfigurationError, CreationUnknownError, ProtocolError, TranscriptTransportError, get_transcript


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Get a transcript for one explicit Instagram Reel URL.")
    parser.add_argument("url", help="bare HTTPS Instagram Reel URL")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = get_transcript(args.url)
    except CreationUnknownError as exc:
        print(f"Run creation status is unknown. Reconcile before retrying: {exc}", file=sys.stderr)
        return 10
    except (ConfigurationError, ProtocolError, TranscriptTransportError) as exc:
        print(f"Transcript request failed: {exc}", file=sys.stderr)
        return 2

    if result.status != "success":
        print(json.dumps({"status": result.status, "error": result.error, "run_id": result.run_id}, ensure_ascii=False))
        return 1

    print(result.text)
    print(f"Segments: {len(result.segments)}")
    # The original item retains fields such as title, duration, timestamp and unknown Actor fields.
    item = result.items[0] if result.items else {}
    print(json.dumps({"title": item.get("title"), "duration": item.get("duration")}, ensure_ascii=False))
    # Keep `item` or serialize it to your own destination if you need all original Actor fields.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
