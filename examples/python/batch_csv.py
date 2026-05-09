from __future__ import annotations

import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from apify_client import ApifyClient
from dotenv import load_dotenv


DEFAULT_ACTOR_ID = "apple_yang/instagram-transcripts-scraper"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = REPO_ROOT / "sample-data" / "instagram-reel-urls.csv"
OUTPUT_DIR = REPO_ROOT / "sample-output" / "generated"
RESULTS_FILE = OUTPUT_DIR / "python-batch-results.jsonl"
ERRORS_FILE = OUTPUT_DIR / "python-batch-errors.csv"
MAX_RETRIES = 2


def load_config() -> None:
    load_dotenv(REPO_ROOT / ".env")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Error: {name} is required. Set it in .env or your environment.")
    return value


def parse_max_concurrency() -> int:
    raw_value = os.getenv("MAX_CONCURRENCY", "3")
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise SystemExit("Error: MAX_CONCURRENCY must be an integer.") from exc
    if value < 1:
        raise SystemExit("Error: MAX_CONCURRENCY must be at least 1.")
    return value


def read_urls(csv_path: Path) -> list[str]:
    if not csv_path.exists():
        raise SystemExit(f"Error: CSV file not found: {csv_path}")

    with csv_path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or "videoUrl" not in reader.fieldnames:
            raise SystemExit("Error: CSV must include a videoUrl column.")
        return [row["videoUrl"].strip() for row in reader if row.get("videoUrl", "").strip()]


def fetch_dataset_items(client: ApifyClient, dataset_id: str) -> list[dict[str, Any]]:
    return client.dataset(dataset_id).list_items().items


def first_value(items: list[dict[str, Any]], key: str) -> Any:
    for item in items:
        value = item.get(key)
        if value:
            return value
    return None


def call_actor_once(token: str, actor_id: str, video_url: str, sessionid: str) -> list[dict[str, Any]]:
    client = ApifyClient(token)
    run = client.actor(actor_id).call(
        run_input={
            "videoUrl": video_url,
            "sessionid": sessionid,
        }
    )
    dataset_id = run.get("defaultDatasetId") if run else None
    if not dataset_id:
        raise RuntimeError("Actor run completed without a defaultDatasetId.")
    return fetch_dataset_items(client, dataset_id)


def build_result(source_url: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    text = first_value(items, "text")
    segments = first_value(items, "segments")
    err_msg = first_value(items, "errMsg")
    if err_msg:
        status = "actor_error"
    elif not items:
        status = "empty"
    else:
        status = "success"

    return {
        "sourceUrl": source_url,
        "status": status,
        "itemCount": len(items),
        "text": text or "",
        "segments": segments or [],
        "errMsg": err_msg or "",
        "rawItems": items,
    }


def process_url(token: str, actor_id: str, video_url: str, sessionid: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            items = call_actor_once(token, actor_id, video_url, sessionid)
            return build_result(video_url, items)
        except Exception as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(2**attempt)

    raise RuntimeError(str(last_error) if last_error else "Unknown error")


def write_results(results: list[dict[str, Any]], errors: list[dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with RESULTS_FILE.open("w", encoding="utf-8") as file:
        for result in results:
            file.write(json.dumps(result, ensure_ascii=False) + "\n")

    with ERRORS_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["sourceUrl", "error"])
        writer.writeheader()
        writer.writerows(errors)


def main() -> None:
    load_config()

    token = require_env("APIFY_TOKEN")
    actor_id = os.getenv("APIFY_ACTOR_ID", DEFAULT_ACTOR_ID)
    sessionid = os.getenv("INSTAGRAM_SESSIONID", "")
    csv_path = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else DEFAULT_CSV
    max_concurrency = parse_max_concurrency()
    urls = read_urls(csv_path)

    if not urls:
        raise SystemExit("Error: CSV does not contain any videoUrl values.")

    print(f"Actor ID: {actor_id}")
    print(f"Total URLs: {len(urls)}")
    print(f"Max concurrency: {max_concurrency}")
    print("Higher concurrency may increase Apify usage cost and rate-limit risk.")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    processed = 0
    success = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        future_to_url = {
            executor.submit(process_url, token, actor_id, video_url, sessionid): video_url
            for video_url in urls
        }

        for future in as_completed(future_to_url):
            source_url = future_to_url[future]
            processed += 1
            try:
                result = future.result()
                results.append(result)
                success += 1
            except Exception as exc:
                errors.append({"sourceUrl": source_url, "error": str(exc)})
                failed += 1

            print(
                f"Progress: total={len(urls)} processed={processed} "
                f"success={success} failed={failed}"
            )

    write_results(results, errors)

    print(f"Results path: {RESULTS_FILE}")
    print(f"Errors path: {ERRORS_FILE}")


if __name__ == "__main__":
    main()
