#!/usr/bin/env bash
set -euo pipefail

# Runs one real Gate -> Garden smoke test and stores all evidence together.
# The runner never deletes Redis/Mongo data; reset must be an explicit action.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER_BIN="${DOCKER_BIN:-docker}"
IMAGE="${IMAGE:-severtest/client:local}"
NETWORK="${NETWORK:-master_garden_network}"
GATE_HOST="${GATE_HOST:-master_garden_gate}"
GATE_PORT="${GATE_PORT:-26002}"
UID_VALUE="${UID_VALUE:-10000912}"
ACTIVITY_ID="${ACTIVITY_ID:-90001}"
CASE_FILE="${CASE_FILE:-/cases/milestone-v2-submit.json}"
TEST_SID="${TEST_SID:-severtest-local}"
REDIS_CONTAINER="${REDIS_CONTAINER:-${GATE_HOST%_gate}_redis}"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT_DIR/reports}"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="$OUTPUT_DIR/$RUN_ID"

mkdir -p "$RUN_DIR"

echo "[severtest] run=$RUN_ID uid=$UID_VALUE activity=$ACTIVITY_ID"
echo "[severtest] network=$NETWORK gate=$GATE_HOST:$GATE_PORT"

if [[ "${BUILD:-1}" == "1" ]]; then
  "$DOCKER_BIN" build \
    --build-context sunnyisland="$ROOT_DIR/../sunnyisland" \
    -f "$ROOT_DIR/Dockerfile.client" \
    -t "$IMAGE" "$ROOT_DIR"
fi

if ! "$DOCKER_BIN" network inspect "$NETWORK" >/dev/null 2>&1; then
  echo "[severtest] Docker network not found: $NETWORK" >&2
  exit 2
fi

if [[ "${PREPARE_SID:-1}" == "1" ]]; then
  if ! "$DOCKER_BIN" inspect "$REDIS_CONTAINER" >/dev/null 2>&1; then
    echo "[severtest] Redis container not found: $REDIS_CONTAINER" >&2
    echo "[severtest] set REDIS_CONTAINER explicitly, or use PREPARE_SID=0" >&2
    exit 2
  fi
  echo "[severtest] preparing local SID in $REDIS_CONTAINER"
  "$DOCKER_BIN" exec "$REDIS_CONTAINER" redis-cli \
    SET "user:login:sid:$UID_VALUE" "$TEST_SID" EX 86400 >/dev/null
fi

# The client exits non-zero on assertion failure. Preserve its report and logs
# before returning the same status to CI or a developer shell.
set +e
"$DOCKER_BIN" run --rm \
  --network "$NETWORK" \
  -v "$RUN_DIR:/reports" \
  "$IMAGE" \
  -uid "$UID_VALUE" \
  -host "$GATE_HOST" \
  -port "$GATE_PORT" \
  -output /reports/milestone-v2-smoke.json \
  -case "$CASE_FILE" \
  >"$RUN_DIR/client.log" 2>&1
CLIENT_STATUS=$?
set -e

REPORT="$RUN_DIR/milestone-v2-smoke.json"
if [[ -f "$REPORT" ]]; then
  cp "$REPORT" "$OUTPUT_DIR/milestone-v2-smoke-latest.json"
fi

# Container names are configurable because Compose prefixes differ by branch.
GARDEN_CONTAINER="${GARDEN_CONTAINER:-severtest_garden}"
if "$DOCKER_BIN" inspect "$GARDEN_CONTAINER" >/dev/null 2>&1; then
  "$DOCKER_BIN" logs --since "${LOG_SINCE:-10m}" "$GARDEN_CONTAINER" >"$RUN_DIR/garden.log" 2>&1 || true
fi

cat >"$RUN_DIR/metadata.json" <<EOF
{
  "run_id": "$RUN_ID",
  "uid": $UID_VALUE,
  "activity_id": $ACTIVITY_ID,
  "network": "$NETWORK",
  "gate_host": "$GATE_HOST",
  "gate_port": $GATE_PORT,
  "redis_container": "$REDIS_CONTAINER",
  "sid_prepared": ${PREPARE_SID:-1},
  "client_exit_code": $CLIENT_STATUS,
  "report": "$REPORT"
}
EOF

echo "[severtest] evidence=$RUN_DIR"
if [[ $CLIENT_STATUS -ne 0 ]]; then
  echo "[severtest] FAILED; see $RUN_DIR/client.log and $RUN_DIR/garden.log" >&2
  exit "$CLIENT_STATUS"
fi
echo "[severtest] PASSED; report=$REPORT"
