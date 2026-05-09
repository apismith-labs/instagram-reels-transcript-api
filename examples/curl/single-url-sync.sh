#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

EXPORTED_APIFY_TOKEN="${APIFY_TOKEN-}"
EXPORTED_APIFY_ACTOR_ID="${APIFY_ACTOR_ID-}"
EXPORTED_INSTAGRAM_REEL_URL="${INSTAGRAM_REEL_URL-}"
EXPORTED_INSTAGRAM_SESSIONID="${INSTAGRAM_SESSIONID-}"

# .env values containing special characters such as & must be quoted.
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  source "${REPO_ROOT}/.env"
  set +a
fi

if [[ -n "${EXPORTED_APIFY_TOKEN}" ]]; then
  APIFY_TOKEN="${EXPORTED_APIFY_TOKEN}"
fi

if [[ -n "${EXPORTED_APIFY_ACTOR_ID}" ]]; then
  APIFY_ACTOR_ID="${EXPORTED_APIFY_ACTOR_ID}"
fi

if [[ -n "${EXPORTED_INSTAGRAM_REEL_URL}" ]]; then
  INSTAGRAM_REEL_URL="${EXPORTED_INSTAGRAM_REEL_URL}"
fi

if [[ -n "${EXPORTED_INSTAGRAM_SESSIONID}" ]]; then
  INSTAGRAM_SESSIONID="${EXPORTED_INSTAGRAM_SESSIONID}"
fi

ACTOR_ID="${APIFY_ACTOR_ID:-apple_yang/instagram-transcripts-scraper}"
OUTPUT_DIR="${REPO_ROOT}/sample-output/generated"
OUTPUT_FILE="${OUTPUT_DIR}/curl-single-url-response.json"

if [[ -z "${APIFY_TOKEN:-}" ]]; then
  echo "Error: APIFY_TOKEN is required. Set it in your environment or local .env file." >&2
  exit 1
fi

if [[ -z "${INSTAGRAM_REEL_URL:-}" ]]; then
  echo "Error: INSTAGRAM_REEL_URL is required. Set it to the Instagram Reel URL you want to process." >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"

ACTOR_ID_FOR_URL="${ACTOR_ID//\//~}"
API_URL="https://api.apify.com/v2/acts/${ACTOR_ID_FOR_URL}/run-sync-get-dataset-items"

json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "${value}"
}

VIDEO_URL_JSON="$(json_escape "${INSTAGRAM_REEL_URL}")"
SESSIONID_JSON="$(json_escape "${INSTAGRAM_SESSIONID:-}")"

# The synchronous dataset-items endpoint is convenient for quick validation.
# Longer Actor runs may time out here; production workflows should use an async run flow.
echo "Using Actor ID: ${ACTOR_ID}"
echo "Running request..."

curl \
  --fail \
  --silent \
  --show-error \
  --request POST "${API_URL}" \
  --header "Authorization: Bearer ${APIFY_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "$(printf '{"videoUrl":"%s","sessionid":"%s"}' "${VIDEO_URL_JSON}" "${SESSIONID_JSON}")" \
  --output "${OUTPUT_FILE}"

echo "Saved raw JSON response to: ${OUTPUT_FILE}"
