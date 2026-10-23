# Java 17 Release Quick Start

This repository Release is versioned `v0.10.0`. The Java example remains an independently
versioned Maven project at `0.1.0`; it is not published to Maven Central. The release asset is named
`instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar`, matching the Maven output name and
making the Java artifact version explicit.

## Check the downloaded artifact

Verify the JAR against `SHA256SUMS.txt`, then run the no-network CLI checks:

```sh
shasum -a 256 -c SHA256SUMS.txt
java -jar instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar --version
java -jar instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar --help
```

`--version` prints `0.1.0`. These commands do not read credentials or create an Actor Run.

## Run one Single URL request

Use Java 17. Set `APIFY_TOKEN` in the process environment or a secret manager; do not put it in
the command line, source, journal, or output. A real invocation creates a potentially billable Run.

macOS/Linux:

```sh
export APIFY_TOKEN="your_apify_token"
java -jar instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar single \
  "https://www.instagram.com/reel/your_reel_id/" \
  --require-charge-cap --max-total-charge-usd 0.10
```

PowerShell:

```powershell
$env:APIFY_TOKEN = "your_apify_token"
java -jar instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar single `
  "https://www.instagram.com/reel/your_reel_id/" `
  --require-charge-cap --max-total-charge-usd 0.10
```

The positive cap is a per-Run Apify option, not a guarantee of the final account bill. Review the
[Java guide](README.md) before using Bulk, Profile, CSV, or Resume. Java Profile collects post
metadata, not transcripts; its three-account Live acceptance was PARTIAL.
