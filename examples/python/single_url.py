from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from apify_client import ApifyClient
from dotenv import load_dotenv


DEFAULT_ACTOR_ID = "apple_yang/instagram-transcripts-scraper"
REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "sample-output" / "generated"
OUTPUT_FILE = OUTPUT_DIR / "python-single-url-response.json"


def load_config() -> None:
    load_dotenv(REPO_ROOT / ".env")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Error: {name} is required. Set it in .env or your environment.")
    return value


def fetch_dataset_items(client: ApifyClient, dataset_id: str) -> list[dict[str, Any]]:
    return client.dataset(dataset_id).list_items().items


def first_value(items: list[dict[str, Any]], key: str) -> Any:
    for item in items:
        value = item.get(key)
        if value:
            return value
    return None


def main() -> None:
    load_config()

    token = require_env("APIFY_TOKEN")
    actor_id = os.getenv("APIFY_ACTOR_ID", DEFAULT_ACTOR_ID)
    sessionid = os.getenv("INSTAGRAM_SESSIONID", "")
    reel_url = sys.argv[1] if len(sys.argv) > 1 else os.getenv("INSTAGRAM_REEL_URL")

    if not reel_url:
        raise SystemExit(
            "Error: INSTAGRAM_REEL_URL is required. Set it in .env or pass it as a CLI argument."
        )

    client = ApifyClient(token)
    run_input = {
        "videoUrl": reel_url,
        "sessionid": sessionid,
    }

    print(f"Actor ID: {actor_id}")
    print("Running request...")

    run = client.actor(actor_id).call(run_input=run_input)
    dataset_id = run.get("defaultDatasetId") if run else None
    if not dataset_id:
        raise SystemExit("Error: Actor run completed without a defaultDatasetId.")

    items = fetch_dataset_items(client, dataset_id)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    text = first_value(items, "text")
    segments = first_value(items, "segments")
    err_msg = first_value(items, "errMsg")

    print(f"Output path: {OUTPUT_FILE}")
    print(f"Items: {len(items)}")
    print(f"Transcript characters: {len(text) if isinstance(text, str) else 0}")
    print(f"Segments: {len(segments) if isinstance(segments, list) else 0}")
    if err_msg:
        print(f"errMsg: {err_msg}")


if __name__ == "__main__":
    main()
