# Quick Start

Run one public Instagram Reel URL through the Apify Actor and print its transcript. Running this Actor may incur Apify charges. Review [current pricing](https://apify.com/apple_yang/instagram-transcripts-scraper/pricing) before starting a Run. The examples pin Build `0.0.50`, request a positive per-Run charge cap, and set `restartOnError=false`. A requested cap is a protective Run option, not an absolute final-bill guarantee.

Use a public URL you are allowed to process. Replace `REPLACE_WITH_A_REAL_SHORTCODE` with its shortcode. Set `APIFY_TOKEN` in your shell's environment or secret manager; the token is sent only in an `Authorization: Bearer` header, never in a URL or source file. Do not paste it into shell history, logs, or Git.

All examples make one Run-creation `POST`, print the Run ID as soon as the response provides it, poll that same Run with `GET`, then read its default Dataset with `GET`. **A create HTTP error, connection loss, timeout, or ambiguous response is not retried. Exit nonzero and print: “Reconcile the existing Run in Apify before retrying.”** A missing token or other pre-request configuration error sends no request.

The examples poll up to 300 times with roughly one-second intervals (about five minutes, plus request time). If the Run is still `READY` or `RUNNING` at that ceiling, continue polling the same Run with `GET`; do not create another Run. A terminal status other than `SUCCEEDED` is reported as a failure.

## cURL

Requires `curl`, `jq`, and Bash. Export `APIFY_TOKEN` using your preferred secure shell setup, then run:

```bash
: "${APIFY_TOKEN:?Set APIFY_TOKEN in your environment first}"
API='https://api.apify.com/v2'
ACTOR='apple_yang~instagram-transcripts-scraper'
INPUT='{"videoUrl":"https://www.instagram.com/reel/REPLACE_WITH_A_REAL_SHORTCODE/"}'

# This is the only create POST. Any HTTP/connection/response error stops here; never repeat it.
created=$(curl --fail --silent --show-error \
  -X POST "$API/acts/$ACTOR/runs?build=0.0.50&restartOnError=false&maxTotalChargeUsd=0.10" \
  -H "Authorization: Bearer $APIFY_TOKEN" \
  -H 'Content-Type: application/json' \
  --data "$INPUT") || { echo 'Run creation failed or is uncertain. Reconcile the existing Run in Apify before retrying.' >&2; exit 1; }
run_id=$(jq -er '.data.id | strings | select(length > 0)' <<<"$created") || { echo 'Run creation response is ambiguous. Reconcile the existing Run in Apify before retrying.' >&2; exit 1; }
dataset_id=$(jq -er '.data.defaultDatasetId | strings | select(length > 0)' <<<"$created") || { echo 'Run creation response is ambiguous. Reconcile the existing Run in Apify before retrying.' >&2; exit 1; }
printf 'Run ID: %s\n' "$run_id"

status=''
for _ in $(seq 1 300); do
  if ! run=$(curl --fail --silent --show-error \
    -H "Authorization: Bearer $APIFY_TOKEN" "$API/actor-runs/$run_id"); then
    echo "Run $run_id could not be polled. Continue with GET for this same Run; do not create another Run." >&2
    exit 1
  fi
  status=$(jq -er '.data.status' <<<"$run") || { echo "Run $run_id status response was invalid. Reconcile this same Run; do not create another Run." >&2; exit 1; }
  case "$status" in
    SUCCEEDED|FAILED|ABORTED|TIMED-OUT) break ;;
  esac
  sleep 1
done
case "$status" in
  SUCCEEDED|FAILED|ABORTED|TIMED-OUT) ;;
  *)
  printf 'Polling ceiling reached for Run %s (status=%s). Continue polling this same Run with GET; do not create another Run.\n' "$run_id" "$status" >&2
  exit 1
    ;;
esac
if [ "$status" != SUCCEEDED ]; then
  printf 'Run %s finished without SUCCEEDED (status=%s). Do not create a replacement Run.\n' "$run_id" "$status" >&2
  exit 1
fi

items=$(curl --fail --silent --show-error \
  -H "Authorization: Bearer $APIFY_TOKEN" \
  "$API/datasets/$dataset_id/items?format=json")
jq -er '
  if length == 0 then error("Dataset is empty") else .[0] end
  | if ((.errMsg // "") != "") then error("Actor item reported errMsg")
    elif ((.text // "") | type) != "string" or (.text | length) == 0 then error("No transcript text in first item")
    else "Transcript:\n\(.text)" end
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
TOKEN = os.environ.get("APIFY_TOKEN")
if not TOKEN:
    raise SystemExit("Set APIFY_TOKEN in your environment; no request was sent.")

def request(method, url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    })
    with urlopen(req, timeout=60) as response:
        return json.load(response)

# One create POST only. Any create exception or malformed response is not retried.
try:
    created = request("POST", f"{API}/acts/{ACTOR}/runs?build=0.0.50&restartOnError=false&maxTotalChargeUsd=0.10", {
        "videoUrl": "https://www.instagram.com/reel/REPLACE_WITH_A_REAL_SHORTCODE/"
    })
    run_id = created["data"]["id"]
    dataset_id = created["data"]["defaultDatasetId"]
    if not isinstance(run_id, str) or not run_id or not isinstance(dataset_id, str) or not dataset_id:
        raise ValueError("missing Run or Dataset ID")
except Exception:
    raise SystemExit("Run creation failed or is uncertain. Reconcile the existing Run in Apify before retrying.")
print(f"Run ID: {run_id}", flush=True)

status = None
for _ in range(300):
    run = request("GET", f"{API}/actor-runs/{run_id}")
    status = run["data"]["status"]
    if status in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
        break
    time.sleep(1)
if status not in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
    raise SystemExit(f"Polling ceiling reached for Run {run_id} (status={status}). Continue polling this same Run with GET; do not create another Run.")
if status != "SUCCEEDED":
    raise SystemExit(f"Run {run_id} finished without SUCCEEDED (status={status}); do not create a replacement Run")

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
if (!token) {
  console.error('Set APIFY_TOKEN in your environment; no request was sent.');
  process.exit(1);
}

async function request(method, url, body) {
  const response = await fetch(url, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) throw new Error(`Apify API returned HTTP ${response.status}`);
  return response.json();
}

// One create POST only. Any create exception or malformed response is not retried.
let created;
let runId;
let datasetId;
try {
  created = await request('POST',
    `${API}/acts/${ACTOR}/runs?build=0.0.50&restartOnError=false&maxTotalChargeUsd=0.10`,
    { videoUrl: 'https://www.instagram.com/reel/REPLACE_WITH_A_REAL_SHORTCODE/' });
  runId = created?.data?.id;
  datasetId = created?.data?.defaultDatasetId;
  if (typeof runId !== 'string' || !runId || typeof datasetId !== 'string' || !datasetId) throw new Error('malformed response');
} catch {
  console.error('Run creation failed or is uncertain. Reconcile the existing Run in Apify before retrying.');
  process.exit(1);
}
console.log(`Run ID: ${runId}`);

let status;
for (let i = 0; i < 300; i += 1) {
  const run = await request('GET', `${API}/actor-runs/${runId}`);
  status = run.data.status;
  if (['SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'].includes(status)) break;
  await new Promise(resolve => setTimeout(resolve, 1000));
}
if (!['SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'].includes(status)) {
  console.error(`Polling ceiling reached for Run ${runId} (status=${status}). Continue polling this same Run with GET; do not create another Run.`);
  process.exit(1);
}
if (status !== 'SUCCEEDED') {
  console.error(`Run ${runId} finished without SUCCEEDED (status=${status}); do not create a replacement Run`);
  process.exit(1);
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
