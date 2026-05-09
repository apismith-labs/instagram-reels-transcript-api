# Input and output fields

This document describes the baseline input and output fields for the Apify Actor `apple_yang/instagram-transcripts-scraper`.

Actor page: [Instagram Transcripts Scraper](https://apify.com/apple_yang/instagram-transcripts-scraper)

## Actor input fields

The Actor input uses this shape:

```json
{
  "videoUrl": "https://www.instagram.com/reel/your_reel_id/",
  "sessionid": ""
}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `videoUrl` | string | Yes | Instagram Reel URL to process. |
| `sessionid` | string | No | Optional Instagram session value. Leave blank unless your integration specifically requires it. |

## Important output fields

| Field | Description |
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
| `text` | Transcript text. This is usually the primary field application code consumes. |
| `segments` | Transcript segments, typically useful for timestamped transcript displays. |
| `errMsg` | Error message returned for failed or partially failed processing. |
| `timestamp` | Processing timestamp or transcript timestamp metadata returned by the Actor. |

## Parsing notes

Treat metadata fields as optional. Production integrations should handle missing values and should preserve `errMsg` for failed records.

During early validation, store the raw Actor result alongside any normalized fields your application needs.
