# Use Instagram Reels Transcript API with cURL

This is the fastest way to verify that:

- Your Apify token works.
- The Actor input format is correct.
- Your Instagram Reel URL returns transcript data.

The example uses Apify's synchronous dataset-items endpoint for quick validation. This is useful for testing one Reel URL, but longer runs may time out and should use an async Actor run flow in production.

## Setup

1. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set your values:

   ```bash
   APIFY_TOKEN='your_apify_token_here'
   INSTAGRAM_REEL_URL='https://www.instagram.com/reel/your_reel_id/'
   ```

3. Quote values that contain special characters such as `&` or `?`.

   Optionally set `INSTAGRAM_SESSIONID` if your integration requires it. Do not commit `.env`.

4. Run the example from the repository root:

   ```bash
   bash examples/curl/single-url-sync.sh
   ```

The script auto-loads `.env` from the repository root. Exported environment variables also work; if both exported variables and `.env` values are present, the exported values are used by the script.

## Output

The script saves the raw JSON response to:

```text
sample-output/generated/curl-single-url-response.json
```

Review this file to confirm the response includes transcript fields such as `text`, `segments`, and any returned metadata.
