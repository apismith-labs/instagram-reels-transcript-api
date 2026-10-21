"""Quickstart for Profile post metadata; this mode does not create transcripts."""
from __future__ import annotations

import argparse
import sys
from typing import Callable, Sequence

if __package__:
    from .client import CreationUnknownError, ConfigurationError, ProtocolError, TranscriptTransportError, get_profile_posts
else:
    from client import CreationUnknownError, ConfigurationError, ProtocolError, TranscriptTransportError, get_profile_posts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Instagram Profile post metadata in one Actor Run.")
    parser.add_argument("usernames", nargs="+", help="Explicit Instagram usernames; no default account is used")
    parser.add_argument("--results-limit", type=int, help="Actor resultsLimit; multi-account scope is unverified")
    parser.add_argument("--only-posts-newer-than", help="YYYY-MM-DD or a relative period such as '7 days'")

    def parse_bool(value: str) -> bool:
        lowered = value.lower()
        if lowered not in {"true", "false"}:
            raise argparse.ArgumentTypeError("choose true or false")
        return lowered == "true"

    parser.add_argument("--skip-pinned-posts", type=parse_bool, metavar="true|false")
    parser.add_argument("--include-shares-count", type=parse_bool, metavar="true|false")
    parser.add_argument("--timeout", type=float, help="Overall Run timeout in seconds")
    return parser


def run_cli(argv: Sequence[str] | None = None, *, fetch: Callable = get_profile_posts) -> int:
    """Injectable command handler so argument checks can be tested without a Run."""
    try:
        args = build_parser().parse_args(argv)
        result = fetch(
            args.usernames,
            results_limit=args.results_limit,
            only_posts_newer_than=args.only_posts_newer_than,
            skip_pinned_posts=args.skip_pinned_posts,
            include_shares_count=args.include_shares_count,
            timeout=args.timeout,
        )
    except (ConfigurationError, ProtocolError, TranscriptTransportError, CreationUnknownError) as exc:
        print(f"Request stopped: {exc}", file=sys.stderr)
        return 2

    print(f"Profile result: {result.status}; posts: {len(result.posts)}; dataset_complete: {result.dataset_complete}")
    for post in result.posts:
        print(f"{post.url or '(URL unavailable)'}  type={post.type or '(unknown)'}  status={post.status}")
        if post.owner_username:
            print(f"  owner: {post.owner_username}")
        if post.caption:
            print(f"  caption: {post.caption}")
        if post.video_duration is not None:
            print(f"  videoDuration: {post.video_duration}")
        if post.timestamp is not None:
            print(f"  timestamp: {post.timestamp}")
        if post.error:
            print(f"  detail: {post.error}")
    if result.error:
        print(f"Detail: {result.error}")
    return 0 if result.status == "success" else 1


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
