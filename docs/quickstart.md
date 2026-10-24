# Quick Start

Run one public Instagram Reel URL through the Apify Actor and print its transcript. This starts a real Actor Run and may incur charges. The examples pin Build `0.0.50`, request a `$0.10` per-run charge cap, and set `restartOnError=false`. A requested cap is a protective Run option, not an absolute final-bill guarantee. Review [cost estimation](cost-estimation.md) first.

Use a public URL you are allowed to process. Replace `REPLACE_WITH_A_REAL_SHORTCODE` with its shortcode. Set `APIFY_TOKEN` in your shell's environment or secret manager; the token is sent only in an `Authorization: Bearer` header, never in a URL or source file. Do not paste it into shell history, logs, or Git.

All examples make one Run-creation `POST`, print the Run ID as soon as the response provides it, poll that same Run with `GET`, then read its default Dataset with `GET`. **If the create request times out or its outcome is unclear, stop and reconcile the Run in Apify before doing anything else. Never retry the create `POST` automatically or manually just because the response was lost.**

## cURL

Requires `curl`, `jq`, and Bash. Export `APIFY_TOKEN` using your preferred secure shell setup, then run:

```bash
: "${APIFY_TOKEN:?Set APIFY_TOKEN in your environment first}"
API='https://api.apify.com/v2'
ACTOR='apple_yang~instagram-transcripts-scraper'
INPUT='{"videoUrl":"https://www.instagram.com/reel/REPLACE_WITH_A_REAL_SHORTCODE/"}'

# This is the only create POST. If it times out or returns an ambiguous response, stop; do not repeat it.
created=$(curl --fail --silent --show-error \
  -X POST "$API/acts/$ACTOR/runs?build=0.0.50&restartOnError=false&maxTotalChargeUsd=0.10" \
  -H "Authorization: Bearer $APIFY_TOKEN" \
  -H 'Content-Type: application/json' \
  --data "$INPUT") || { echo 'Run creation response unavailable; reconcile in Apify before retrying.' >&2; exit 1; }
run_id=$(jq -er '.data.id' <<<"$created")
dataset_id=$(jq -er '.data.defaultDatasetId' <<<"$created")
printf 'Run ID: %s\n' "$run_id"

status=''
for _ in $(seq 1 300); do
  run=$(curl --fail --silent --show-error \
    -H "Authorization: Bearer $APIFY_TOKEN" "$API/actor-runs/$run_id")
  status=$(jq -er '.data.status' <<<"$run")
  case "$status" in
    SUCCEEDED|FAILED|ABORTED|TIMED-OUT) break ;;
  esac
  sleep 1
done
if [ "$status" != SUCCEEDED ]; then
  printf 'Run %s ended or did not finish successfully (status=%s). Do not create a replacement Run.\n' "$run_id" "$status" >&2
  exit 1
fi

items=$(curl --fail --silent --show-error \
  -H "Authorization: Bearer $APIFY_TOKEN" \
  "$API/datasets/$dataset_id/items?format=json")
jq -er --arg run_id "$run_id" '
  if length == 0 then error("Dataset is empty") else .[0] end
  | if ((.errMsg // "") != "") then error("Actor item reported errMsg")
    elif ((.text // "") | type) != "string" or (.text | length) == 0 then error("No transcript text in first item")
    else "Run ID: \($run_id)\nTranscript:\n\(.text)" end
' <<<"$items"
```

## Python 3.10+

Uses only the Python standard library. Save the following as `quickstart.py` and run it with `python3 quickstart.py` after setting `APIFY_TOKEN` in the environment.

```python
import json
import os
import time
from urllib.request import Request, urlopen

API = "https://api.apify.com/v2"
ACTOR = "apple_yang~instagram-transcripts-scraper"
TOKEN = os.environ["APIFY_TOKEN"]

def request(method, url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    })
    with urlopen(req, timeout=60) as response:
        return json.load(response)

# One create POST only. If its outcome is unclear, stop and reconcile in Apify; do not retry.
created = request("POST", f"{API}/acts/{ACTOR}/runs?build=0.0.50&restartOnError=false&maxTotalChargeUsd=0.10", {
    "videoUrl": "https://www.instagram.com/reel/REPLACE_WITH_A_REAL_SHORTCODE/"
})
run_id = created["data"]["id"]
dataset_id = created["data"]["defaultDatasetId"]
print(f"Run ID: {run_id}", flush=True)

status = None
for _ in range(300):
    run = request("GET", f"{API}/actor-runs/{run_id}")
    status = run["data"]["status"]
    if status in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
        break
    time.sleep(1)
if status != "SUCCEEDED":
    raise SystemExit(f"Run {run_id} did not succeed (status={status}); do not create a replacement Run")

items = request("GET", f"{API}/datasets/{dataset_id}/items?format=json")
if not items:
    raise SystemExit(f"Run {run_id} succeeded but its Dataset is empty")
item = items[0]
if item.get("errMsg"):
    raise SystemExit(f"Run {run_id} returned an Actor item error; inspect the item securely")
text = item.get("text")
if not isinstance(text, str) or not text:
    raise SystemExit(f"Run {run_id} returned no transcript text")
print("Transcript:")
print(text)
```

## Node.js 18+

Uses the built-in `fetch`; no package install is required. Save as `quickstart.mjs` and run `node quickstart.mjs` after setting `APIFY_TOKEN` in the environment.

```javascript
const API = 'https://api.apify.com/v2';
const ACTOR = 'apple_yang~instagram-transcripts-scraper';
const token = process.env.APIFY_TOKEN;
if (!token) throw new Error('Set APIFY_TOKEN in the environment first');

async function request(method, url, body) {
  const response = await fetch(url, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) throw new Error(`Apify API returned HTTP ${response.status}`);
  return response.json();
}

// One create POST only. If its outcome is unclear, stop and reconcile in Apify; do not retry.
const created = await request('POST',
  `${API}/acts/${ACTOR}/runs?build=0.0.50&restartOnError=false&maxTotalChargeUsd=0.10`,
  { videoUrl: 'https://www.instagram.com/reel/REPLACE_WITH_A_REAL_SHORTCODE/' });
const runId = created.data.id;
const datasetId = created.data.defaultDatasetId;
console.log(`Run ID: ${runId}`);

let status;
for (let i = 0; i < 300; i += 1) {
  const run = await request('GET', `${API}/actor-runs/${runId}`);
  status = run.data.status;
  if (['SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'].includes(status)) break;
  await new Promise(resolve => setTimeout(resolve, 1000));
}
if (status !== 'SUCCEEDED') {
  throw new Error(`Run ${runId} did not succeed (status=${status}); do not create a replacement Run`);
}

const items = await request('GET', `${API}/datasets/${datasetId}/items?format=json`);
if (!Array.isArray(items) || items.length === 0) throw new Error(`Run ${runId} succeeded but its Dataset is empty`);
const item = items[0];
if (item.errMsg) throw new Error(`Run ${runId} returned an Actor item error; inspect the item securely`);
if (typeof item.text !== 'string' || item.text.length === 0) throw new Error(`Run ${runId} returned no transcript text`);
console.log('Transcript:');
console.log(item.text);
```

## What the response means

The create response contains `data.id` (the Run ID) and `data.defaultDatasetId`. A completed Dataset is a JSON array of Actor items. Transcript items use `text`, `segments`, and `errMsg`; an empty `errMsg` is normal, while a non-empty one is an item error. A successful Run status alone does not guarantee a non-empty transcript. See the [field reference](input-output-fields.md) and [error/retry guide](error-handling-and-retries.md).

If the create call's response is lost, do not issue another create request. Reconcile the Run in Apify using the available account history and any recorded Run ID before deciding on a next step.
