# Instagram Reels Transcript API examples using Apify

Developer integration examples for the Apify Actor [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper).

This repository is the starting point for practical examples that help developers validate Instagram Reels transcript extraction and integrate it into apps, internal tools, and batch workflows.

## What this repository will cover

The examples will cover:

- cURL
- Python
- Node.js
- Java
- Go

Every major language example will include:

- Single Instagram Reel URL processing
- Batch CSV processing from `sample-data/instagram-reel-urls.csv`
- Reading credentials from environment variables
- Saving example Actor output to local files
- Basic error handling and retry guidance

The first-stage version of this repository contains the structure, documentation, and placeholders only. Full runnable examples will be added in later phases.

## Apify Actor

- Actor page: [Instagram Transcripts Scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)
- Actor ID: `apple_yang/instagram-transcripts-scraper`

## Authentication

You must provide your own Apify API token.

Create a local `.env` file based on `.env.example`:

```bash
APIFY_TOKEN=your_apify_token_here
```

Never hard-code `APIFY_TOKEN` in source code, scripts, documentation examples, commits, logs, or shared output files.

## Actor input

The Actor accepts input in this shape:

```json
{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/",
  "sessionid": ""
}
```

`videoUrl` should be the Instagram Reel URL to process. `sessionid` is intentionally left blank in the sample configuration unless your use case requires it.

## Important output fields

Expected output can include:

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
```

## Current status

This repository is ready for the next implementation phase, where runnable cURL, Python, Node.js, Java, and Go examples will be added.
