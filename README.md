# Instagram Reels Transcript API examples using Apify

Production-ready developer examples for extracting Instagram Reels transcripts with the Apify Actor [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper).

This repository helps developers validate the Actor quickly and integrate transcript extraction into applications, internal tools, databases, and batch workflows. It includes cURL, Python, Node.js, Java, Go, and Rust examples for single URL and batch CSV processing.

## Apify Actor

- Actor page: [Instagram Transcripts Scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)
- Actor ID: `apple_yang/instagram-transcripts-scraper`

## Quick start

1. Create a local environment file:

   ```bash
   cp .env.example .env
   ```

2. Add your Apify token:

   ```bash
   APIFY_TOKEN='your_apify_token_here'
   APIFY_ACTOR_ID='apple_yang/instagram-transcripts-scraper'
   INSTAGRAM_SESSIONID=''
   MAX_CONCURRENCY=3
   ```

3. Run the cURL quick validation example with a Reel URL as runtime input:

   ```bash
   bash examples/curl/single-url-sync.sh "https://www.instagram.com/reel/your_reel_id/"
   ```

4. Choose a language example for production integration:

   - [Python](examples/python/)
   - [Node.js](examples/nodejs/)
   - [Java](examples/java/)
   - [Go](examples/go/)
   - [Rust](examples/rust/)

## Language examples

| Language | Single URL | Batch CSV | Directory |
| --- | --- | --- | --- |
| cURL | Yes | No | [examples/curl/](examples/curl/) |
| Python | Yes | Yes | [examples/python/](examples/python/) |
| Node.js | Yes | Yes | [examples/nodejs/](examples/nodejs/) |
| Java | Yes | Yes | [examples/java/](examples/java/) |
| Go | Yes | Yes | [examples/go/](examples/go/) |
| Rust | Yes | Yes | [examples/rust/](examples/rust/) |

## Live demo

If you want to test Instagram transcript extraction without writing code, try the web demo built on top of this API: [transcript365.com](https://www.transcript365.com).

## When to use this repo

- Build transcript extraction into your own app.
- Process batches of Instagram Reel URLs.
- Feed transcript text into internal tools, databases, or content analysis pipelines.
- Avoid maintaining your own video download and transcription infrastructure.

## Authentication and input

You must provide your own Apify API token. Do not hard-code `APIFY_TOKEN` in source code, scripts, documentation examples, commits, logs, or shared output files.

Configuration belongs in `.env`:

- `APIFY_TOKEN`
- `APIFY_ACTOR_ID`
- `INSTAGRAM_SESSIONID`
- `MAX_CONCURRENCY`

Instagram Reel URLs are runtime input: pass a single URL as a CLI argument, or provide many URLs in `sample-data/instagram-reel-urls.csv` for batch examples.

## Actor input

```json
{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/",
  "sessionid": ""
}
```

`videoUrl` is the Reel URL for the current request. `sessionid` is optional configuration and should remain blank unless your integration requires it.

## Important output fields

Common fields include:

`url`, `code`, `id`, `title`, `videoUrl`, `audioUrl`, `createTime`, `likeCount`, `commentCount`, `userName`, `userFullName`, `text`, `segments`, `errMsg`, `timestamp`.

See [docs/input-output-fields.md](docs/input-output-fields.md) for the full field reference.

## Repository layout

```text
.
├── docs/
│   ├── batch-processing-guide.md
│   ├── error-handling-and-retries.md
│   ├── input-output-fields.md
│   └── production-integration-checklist.md
├── examples/
│   ├── curl/
│   ├── go/
│   ├── java/
│   ├── nodejs/
│   ├── python/
│   └── rust/
├── sample-data/
│   └── instagram-reel-urls.csv
└── sample-output/
    └── .gitkeep
```

## License

This project is licensed under the MIT License.
