# Prompt Recipes for Instagram Reels Transcript Analysis

Use these prompt templates after extracting transcript data with the Apify Actor [apple_yang/instagram-transcripts-scraper](https://apify.com/apple_yang/instagram-transcripts-scraper).

Assume your application passes some or all of these fields:

- `{{transcript}}`
- `{{segments}}`
- `{{creator_username}}`
- `{{caption}}`
- `{{like_count}}`
- `{{comment_count}}`
- `{{source_url}}`

## Summarize a Reel

```text
Summarize this Instagram Reel in 5 bullet points.

Creator: {{creator_username}}
Caption: {{caption}}
Transcript:
{{transcript}}

Include the main topic, key claims, and final takeaway.
```

## Extract hook and CTA

```text
Analyze this Reel transcript and extract:
1. The opening hook
2. The main promise or argument
3. The call to action
4. Whether the CTA is explicit or implied

Transcript:
{{transcript}}
```

## Analyze why a Reel may perform well

```text
Analyze why this Instagram Reel may perform well.

Creator: {{creator_username}}
Likes: {{like_count}}
Comments: {{comment_count}}
Caption: {{caption}}
Transcript:
{{transcript}}

Focus on hook strength, clarity, emotional trigger, pacing, specificity, and CTA.
```

## Convert a Reel into a blog outline

```text
Turn this Reel transcript into a blog post outline.

Transcript:
{{transcript}}

Return:
- SEO-friendly title
- Suggested introduction
- H2/H3 outline
- Key examples to include
- Suggested conclusion
```

## Rewrite a Reel script for another platform

```text
Rewrite this Instagram Reel script for {{target_platform}}.

Original creator: {{creator_username}}
Original transcript:
{{transcript}}

Keep the core message, adapt the tone and structure for {{target_platform}}, and suggest a platform-native CTA.
```

## Extract product mentions

```text
Extract all product, brand, feature, and offer mentions from this Reel.

Caption: {{caption}}
Transcript:
{{transcript}}

Return a table with:
- Mention
- Type
- Exact phrase
- Context
- Sentiment or framing
```

## Competitor content analysis

```text
Analyze this competitor Reel.

Creator: {{creator_username}}
Source: {{source_url}}
Caption: {{caption}}
Transcript:
{{transcript}}

Return:
- Target audience
- Pain points mentioned
- Product or category positioning
- Hook style
- CTA
- Ideas our team could test without copying directly
```

## Generate ad creative insights

```text
Review this Reel as an ad creative strategist.

Transcript:
{{transcript}}
Segments:
{{segments}}

Identify the hook, problem, solution, proof points, objections handled, CTA, and 3 testable creative angles.
```

## Translate transcript

```text
Translate this Reel transcript into {{target_language}}.

Transcript:
{{transcript}}

Preserve meaning, keep names and product terms unchanged, and return a natural translation suitable for subtitles.
```

## Generate subtitle-friendly text

```text
Convert this transcript into subtitle-friendly text.

Segments:
{{segments}}
Transcript:
{{transcript}}

Return short lines that are easy to read on mobile. Keep the original meaning and avoid long sentences.
```
