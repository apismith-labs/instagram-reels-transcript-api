# Input and output fields

This page documents the foundational input and output fields used by the Apify Actor `apple_yang/instagram-transcripts-scraper`.

Actor page: [Instagram Transcripts Scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

## Input

```json
{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/",
  "sessionid": ""
}
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `videoUrl` | string | Yes | Instagram Reel URL to process. |
| `sessionid` | string | No | Optional Instagram session value. Leave blank unless your integration requires it. |

## Output fields

| Field | Notes |
| --- | --- |
| `url` | Source Instagram Reel URL or canonical URL returned by the Actor. |
| `code` | Instagram shortcode or Reel code when available. |
| `pk` | Instagram media primary key when available. |
| `id` | Media identifier when available. |
| `title` | Reel title or caption-derived title when available. |
| `img` | Thumbnail or image URL when available. |
| `videoUrl` | Direct or processed video URL when available. |
| `audioUrl` | Direct or processed audio URL when available. |
| `createTime` | Creation timestamp or time value returned by the Actor. |
| `likeCount` | Number of likes when available. |
| `commentCount` | Number of comments when available. |
| `userPk` | Instagram user primary key when available. |
| `userName` | Instagram username. |
| `userFullName` | Instagram display name. |
| `avatarUri` | User avatar URL when available. |
| `text` | Transcript text. This is usually the main field application code consumes. |
| `segments` | Transcript segments, typically useful for timestamped transcript displays. |
| `errMsg` | Error message returned for failed or partially failed processing. |
| `timestamp` | Processing timestamp or transcript timestamp metadata returned by the Actor. |

## Practical parsing notes

Treat optional metadata fields as nullable. Production integrations should rely primarily on `text`, `segments`, `url`, and error fields, then use engagement and profile metadata opportunistically.

Store the raw Actor result during early integration testing. Once your downstream schema is stable, map only the fields your application needs.
