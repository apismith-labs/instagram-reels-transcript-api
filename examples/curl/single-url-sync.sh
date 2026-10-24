#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

EXPORTED_APIFY_TOKEN="${APIFY_TOKEN-}"
EXPORTED_APIFY_ACTOR_ID="${APIFY_ACTOR_ID-}"
EXPORTED_APIFY_MAX_TOTAL_CHARGE_USD="${APIFY_MAX_TOTAL_CHARGE_USD-}"
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

if [[ -n "${EXPORTED_APIFY_MAX_TOTAL_CHARGE_USD}" ]]; then
  APIFY_MAX_TOTAL_CHARGE_USD="${EXPORTED_APIFY_MAX_TOTAL_CHARGE_USD}"
fi

if [[ -n "${EXPORTED_INSTAGRAM_REEL_URL}" ]]; then
  INSTAGRAM_REEL_URL="${EXPORTED_INSTAGRAM_REEL_URL}"
fi

if [[ -n "${EXPORTED_INSTAGRAM_SESSIONID}" ]]; then
  INSTAGRAM_SESSIONID="${EXPORTED_INSTAGRAM_SESSIONID}"
fi

ACTOR_ID="${APIFY_ACTOR_ID:-apple_yang/instagram-transcripts-scraper}"
REEL_URL="${1:-${INSTAGRAM_REEL_URL:-}}"
MAX_TOTAL_CHARGE_USD="${APIFY_MAX_TOTAL_CHARGE_USD:-}"
OUTPUT_DIR="${REPO_ROOT}/sample-output/generated"

if [[ -z "${APIFY_TOKEN:-}" ]]; then
  echo "Error: APIFY_TOKEN is required. Set it in your environment or local .env file." >&2
  exit 1
fi

if [[ -z "${REEL_URL}" ]]; then
  echo "Error: Pass an Instagram Reel URL as a CLI argument." >&2
  exit 1
fi

if [[ ! "${MAX_TOTAL_CHARGE_USD}" =~ ^[0-9]+([.][0-9]+)?$ ]] || \
   ! awk -v cap="${MAX_TOTAL_CHARGE_USD}" 'BEGIN { exit !(cap + 0 > 0) }'; then
  echo "Error: APIFY_MAX_TOTAL_CHARGE_USD must be a positive number; no request was sent." >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"

OUTPUT_STAGING=""
OUTPUT_RECOVERY_COPY=""
PRESERVE_STAGING=0
PRESERVE_RECOVERY_COPY=0
cleanup_staging() {
  if [[ -n "${OUTPUT_STAGING}" && "${PRESERVE_STAGING}" -eq 0 ]]; then
    rm -f "${OUTPUT_STAGING}"
  fi
  if [[ -n "${OUTPUT_RECOVERY_COPY}" && "${PRESERVE_RECOVERY_COPY}" -eq 0 ]]; then
    rm -f "${OUTPUT_RECOVERY_COPY}"
  fi
}
trap cleanup_staging EXIT

# Reserve a collision-resistant temporary path; no previous result is overwritten.
OUTPUT_STAGING="$(mktemp "${OUTPUT_DIR}/.curl-single-url.XXXXXXXXXX")"
STAGING_NAME="${OUTPUT_STAGING##*/}"
OUTPUT_NONCE="${STAGING_NAME#.curl-single-url.}"
OUTPUT_FILE="${OUTPUT_DIR}/curl-single-url-${OUTPUT_NONCE}.json"

ACTOR_ID_FOR_URL="${ACTOR_ID//\//~}"
API_URL="https://api.apify.com/v2/acts/${ACTOR_ID_FOR_URL}/run-sync-get-dataset-items?build=0.0.50&restartOnError=false&maxTotalChargeUsd=${MAX_TOTAL_CHARGE_USD}"

json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "${value}"
}

VIDEO_URL_JSON="$(json_escape "${REEL_URL}")"
SESSIONID_JSON="$(json_escape "${INSTAGRAM_SESSIONID:-}")"
if [[ -n "${SESSIONID_JSON}" ]]; then
  INPUT_JSON="$(printf '{"videoUrl":"%s","sessionid":"%s"}' "${VIDEO_URL_JSON}" "${SESSIONID_JSON}")"
else
  INPUT_JSON="$(printf '{"videoUrl":"%s"}' "${VIDEO_URL_JSON}")"
fi

# The synchronous dataset-items endpoint is convenient for quick validation.
# Longer Actor runs may time out here; production workflows should use an async run flow.
echo "Using Actor ID: ${ACTOR_ID}"
echo "Running one synchronous request with Build 0.0.50 and the requested per-Run charge cap..."

if ! curl \
  --fail \
  --silent \
  --show-error \
  --request POST "${API_URL}" \
  --header "Authorization: Bearer ${APIFY_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "${INPUT_JSON}" \
  --output "${OUTPUT_STAGING}"; then
  echo "The synchronous request failed or its outcome is unknown. Do not retry the POST automatically; reconcile usage/run history first." >&2
  exit 1
fi

# The staging file and final path are in the same directory, so mv uses a same-filesystem
# rename. The mktemp nonce is exclusive, and -n is a second guard against replacing an
# existing successful result if a name collision occurs.
response_sha256() {
  local checksum
  checksum="$(shasum -a 256 "${1}" 2>/dev/null)" || return 1
  printf '%s\n' "${checksum%% *}"
}

EXPECTED_RESPONSE_SHA256="$(response_sha256 "${OUTPUT_STAGING}")" || {
  PRESERVE_STAGING=1
  echo "The request succeeded, but the downloaded response could not be verified. It is preserved at: ${OUTPUT_STAGING}. Do not retry the POST; inspect the file manually." >&2
  exit 1
}

# -e does not detect a dangling symlink, so check -L separately. Do this after the
# response arrives: on any collision, retain the downloaded response for recovery.
if [[ -e "${OUTPUT_FILE}" || -L "${OUTPUT_FILE}" ]]; then
  PRESERVE_STAGING=1
  echo "The request succeeded, but the result destination is already occupied. The downloaded response is preserved at: ${OUTPUT_STAGING}. Do not retry the POST; inspect or move that file manually." >&2
  exit 1
fi

# Keep a recovery copy until the renamed destination is verified. This protects the
# downloaded response if an unexpected filesystem race or rename anomaly occurs.
OUTPUT_RECOVERY_COPY="$(mktemp "${OUTPUT_DIR}/.curl-single-url-recovery.XXXXXXXXXX")" || {
  PRESERVE_STAGING=1
  echo "The request succeeded, but a recovery copy could not be prepared. The downloaded response is preserved at: ${OUTPUT_STAGING}. Do not retry the POST." >&2
  exit 1
}
if ! cp -p "${OUTPUT_STAGING}" "${OUTPUT_RECOVERY_COPY}" || \
   [[ "$(response_sha256 "${OUTPUT_RECOVERY_COPY}")" != "${EXPECTED_RESPONSE_SHA256}" ]]; then
  PRESERVE_STAGING=1
  echo "The request succeeded, but its recovery copy could not be verified. The downloaded response is preserved at: ${OUTPUT_STAGING}. Do not retry the POST." >&2
  exit 1
fi

if ! mv -n "${OUTPUT_STAGING}" "${OUTPUT_FILE}" || [[ -e "${OUTPUT_STAGING}" ]]; then
  if [[ -e "${OUTPUT_STAGING}" ]]; then
    PRESERVE_STAGING=1
    echo "The request succeeded, but the response could not be published without overwriting an existing file. The downloaded response is preserved at: ${OUTPUT_STAGING}. Do not retry the POST; inspect or move that file manually." >&2
  elif [[ -e "${OUTPUT_FILE}" ]]; then
    PRESERVE_RECOVERY_COPY=1
    echo "The request succeeded, but publication status could not be confirmed. A file exists at the intended result path: ${OUTPUT_FILE}; the downloaded response is preserved at: ${OUTPUT_RECOVERY_COPY}. Do not retry the POST." >&2
  else
    PRESERVE_RECOVERY_COPY=1
    echo "The request succeeded, but publication status could not be confirmed. The downloaded response is preserved at: ${OUTPUT_RECOVERY_COPY}. Do not retry the POST; reconcile the Run first." >&2
  fi
  exit 1
fi

# mv -n can return success when it skips a move, and a directory at the target can
# otherwise act as a container. Confirm this is a regular, non-symlink file containing
# the exact bytes downloaded before reporting success.
if [[ ! -f "${OUTPUT_FILE}" || -L "${OUTPUT_FILE}" ]]; then
  RECOVERY_FILE="${OUTPUT_FILE}/${STAGING_NAME}"
  if [[ -f "${RECOVERY_FILE}" && ! -L "${RECOVERY_FILE}" ]]; then
    RECOVERY_SHA256="$(response_sha256 "${RECOVERY_FILE}")" || RECOVERY_SHA256=""
    if [[ "${RECOVERY_SHA256}" == "${EXPECTED_RESPONSE_SHA256}" ]]; then
      echo "The request succeeded, but the destination became a directory during publication. The downloaded response is recoverable at: ${RECOVERY_FILE}. Do not retry the POST." >&2
      exit 1
    fi
  fi
  if [[ -e "${OUTPUT_STAGING}" ]]; then
    PRESERVE_STAGING=1
    echo "The request succeeded, but the result destination is not a regular file. The downloaded response is preserved at: ${OUTPUT_STAGING}. Do not retry the POST." >&2
  else
    PRESERVE_RECOVERY_COPY=1
    echo "The request succeeded, but no regular result file could be verified at ${OUTPUT_FILE}. The downloaded response is preserved at: ${OUTPUT_RECOVERY_COPY}. Do not retry the POST." >&2
  fi
  exit 1
fi

PUBLISHED_RESPONSE_SHA256="$(response_sha256 "${OUTPUT_FILE}")" || PUBLISHED_RESPONSE_SHA256=""
if [[ "${PUBLISHED_RESPONSE_SHA256}" != "${EXPECTED_RESPONSE_SHA256}" ]]; then
  PRESERVE_RECOVERY_COPY=1
  echo "The request succeeded, but the published file did not match the downloaded response. The downloaded response is preserved at: ${OUTPUT_RECOVERY_COPY}. Do not retry the POST." >&2
  exit 1
fi

rm -f "${OUTPUT_RECOVERY_COPY}"
OUTPUT_RECOVERY_COPY=""
OUTPUT_STAGING=""

echo "Saved raw JSON response to: ${OUTPUT_FILE}"
