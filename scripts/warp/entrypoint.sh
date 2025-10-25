#!/usr/bin/env bash
set -euo pipefail
set -x
install -d -m 0755 /var/lib/cloudflare-warp
install -d -m 0755 /run/dbus

# Clean stale PID file from previous run
rm -f /run/dbus/pid

dbus-daemon --system --fork

/usr/bin/warp-svc &

cleanup() {
  pkill -TERM -f "/usr/bin/warp-svc" || true
}
trap cleanup EXIT

wait_for_warp() {
  for _ in $(seq 1 60); do
    if warp-cli --accept-tos status >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "warp-cli did not become available in time" >&2
  return 1
}

ensure_registration() {
  # Check if registration exists by querying daemon
  if warp-cli --accept-tos registration show 2>/dev/null | grep -qE "Registration|Device ID|Account"; then
    echo "WARP already registered, skipping registration"
    return 0
  fi

  echo "No registration found, creating new registration..."
  if [[ -n "${WARP_LICENSE_KEY:-}" ]]; then
    warp-cli --accept-tos registration new "${WARP_LICENSE_KEY}"
  else
    warp-cli --accept-tos registration new
  fi

  for _ in $(seq 1 20); do
    if warp-cli --accept-tos registration show 2>/dev/null | grep -qE "Registration|Device ID|Account"; then
      echo "Registration successful"
      return 0
    fi
    sleep 1
  done

  echo "Failed to register Cloudflare WARP client" >&2
  return 1
}

connect_warp() {
  warp-cli --accept-tos mode warp

  for _ in $(seq 1 5); do
    if warp-cli --accept-tos connect; then
      return 0
    fi
    sleep 2
  done
  echo "warp-cli connect failed" >&2
  return 1
}

await_connected() {
  echo "Waiting for WARP to connect..."
  for _ in $(seq 1 60); do
  status_output=$(warp-cli --accept-tos status || true)
  if grep -q "Connected" <<<"$status_output"; then
      echo "WARP connected."
      return 0
    fi
    sleep 1
    warp-cli --accept-tos connect >/dev/null 2>&1 || true
  done
  echo "Failed to establish WARP connection" >&2
  return 1
}

wait_for_warp
ensure_registration
connect_warp
await_connected

# Keep the container alive so bot traffic remains tunneled
tail -f /dev/null
