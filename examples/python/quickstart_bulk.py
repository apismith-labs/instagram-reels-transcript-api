"""Small CLI example for one Native Bulk Actor Run (offline-safe to import)."""
from __future__ import annotations

import argparse
import sys
from typing import Callable, Sequence

if __package__:
    from .client import CreationUnknownError, ConfigurationError, ProtocolError, TranscriptTransportError, get_transcripts
else:
    from client import CreationUnknownError, ConfigurationError, ProtocolError, TranscriptTransportError, get_transcripts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transcribe multiple Reel URLs in one Native Bulk Actor Run.")
    parser.add_argument("urls", nargs="+", help="Bare HTTPS Instagram Reel URLs; all URLs are sent in one Run")
    parser.add_argument("--results-limit", type=int, help="Actor resultsLimit input")
    def parse_bool(value: str) -> bool:
        lowered = value.lower()
        if lowered not in {"true", "false"}:
            raise argparse.ArgumentTypeError("choose true or false")
        return lowered == "true"
    parser.add_argument("--skip-pinned-posts", type=parse_bool, metavar="true|false", help="Set skipPinnedPosts")
    parser.add_argument("--include-shares-count", type=parse_bool, metavar="true|false", help="Set includeSharesCount")
    parser.add_argument("--timeout", type=float, help="Overall Run timeout in seconds")
    return parser


def run_cli(argv: Sequence[str] | None = None, *, fetch: Callable = get_transcripts) -> int:
    """Run a parsed CLI request; injectable fetch keeps CLI tests entirely offline."""
    try:
        args = build_parser().parse_args(argv)
        result = fetch(
            args.urls,
            results_limit=args.results_limit,
            skip_pinned_posts=args.skip_pinned_posts,
            include_shares_count=args.include_shares_count,
            timeout=args.timeout,
        )
    except (ConfigurationError, ProtocolError, TranscriptTransportError, CreationUnknownError) as exc:
        print(f"Request stopped: {exc}", file=sys.stderr)
        return 2

    for row in result.results:
        print(f"{row.url}\n  status: {row.status}")
        if row.text is not None:
            print(f"  transcript characters: {len(row.text)}; segments: {len(row.segments)}")
            print(f"  transcript: {row.text}")
        if row.error:
            print(f"  error: {row.error}")
    print(f"Overall: {result.status}; counts={result.counts}; dataset_complete={result.dataset_complete}")
    if result.extra_results:
        print(f"Unmapped extra Dataset items: {len(result.extra_results)}")
    if result.error:
        print(f"Run detail: {result.error}")
    return 0 if result.status == "all_success" else 1


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
