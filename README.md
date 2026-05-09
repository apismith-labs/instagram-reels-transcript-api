# Instagram Reels Transcript API examples using Apify

Developer-focused examples for using the Apify Actor [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper) as an Instagram Reels Transcript API.

This repository helps developers quickly validate the Actor and prepare integrations for applications, internal tools, and batch transcript workflows.

## Actor details

- Actor page: [Instagram Transcripts Scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)
- Actor ID: `apple_yang/instagram-transcripts-scraper`

## First-stage scope

This phase includes the repository scaffold, documentation placeholders, and runnable cURL, Python, Node.js, Java, and Go examples.

All planned first-stage language examples are now available.

## Planned examples

This repository will include examples for:

- cURL
- Python
- Node.js
- Java
- Go

Every major language example will include:

- Processing a single Instagram Reel URL
- Processing a batch CSV file
- Reading configuration from environment variables
- Writing example output to `sample-output/`
- Basic error handling and retry guidance

## Authentication

You must provide your own Apify API token.

Create a local `.env` file from `.env.example`:

```bash
APIFY_TOKEN='your_apify_token_here'
APIFY_ACTOR_ID='apple_yang/instagram-transcripts-scraper'
INSTAGRAM_SESSIONID=''
MAX_CONCURRENCY=3
```

Do not hard-code `APIFY_TOKEN` in source code, scripts, documentation examples, commits, logs, or shared output files.

Configuration belongs in `.env`: token, Actor ID, optional session ID, and concurrency. Instagram Reel URLs are runtime input: pass a single URL as a CLI argument, or provide many URLs in `sample-data/instagram-reel-urls.csv` for batch examples.

## Actor input

The Actor input uses this shape:

```json
{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/",
  "sessionid": ""
}
```

`videoUrl` is runtime input for each request. `sessionid` is optional configuration and should remain blank unless your integration specifically requires it.

## Important output fields

Actor output can include these fields:

`url`, `code`, `pk`, `id`, `title`, `img`, `videoUrl`, `audioUrl`, `createTime`, `likeCount`, `commentCount`, `userPk`, `userName`, `userFullName`, `avatarUri`, `text`, `segments`, `errMsg`, `timestamp`.

See [docs/input-output-fields.md](docs/input-output-fields.md) for field notes.

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
│   └── python/
├── sample-data/
│   └── instagram-reel-urls.csv
└── sample-output/
    └── .gitkeep
```

## Current status

The cURL quick validation example is available in `examples/curl/`. Python examples are available in `examples/python/`. Node.js examples are available in `examples/nodejs/`. Java examples are available in `examples/java/`. Go examples are available in `examples/go/`.
