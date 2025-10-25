#!/usr/bin/env bash
set -euo pipefail
set -x

install -d -m 0755 /var/lib/cloudflare-warp

/usr/bin/warp-svc &

cleanup() {
  pkill -TERM -f "/usr/bin/warp-svc" || true
}
trap cleanup EXIT

for _ in $(seq 1 60); do
  if warp-cli --accept-tos status >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! warp-cli --accept-tos registration show | grep -q "Registration:"; then
  warp-cli --accept-tos registration new
fi

warp-cli --accept-tos mode warp

for _ in $(seq 1 3); do
  if warp-cli --accept-tos connect; then
    break
  fi
  sleep 2
done

echo "Waiting for WARP to connect..."
for _ in $(seq 1 60); do
  status_output=$(warp-cli --accept-tos status || true)
  if grep -q "Connected" <<<"$status_output"; then
    echo "WARP connected."
    break
  fi
  sleep 1
  warp-cli --accept-tos connect >/dev/null 2>&1 || true
done

if ! warp-cli --accept-tos status | grep -q "Connected"; then
  echo "Failed to establish WARP connection" >&2
  exit 1
fi

# Keep the container alive so bot traffic remains tunneled
tail -f /dev/null
