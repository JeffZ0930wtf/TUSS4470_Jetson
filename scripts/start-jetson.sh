#!/usr/bin/env sh
# Start the real Jetson deployment and stop once Core, Bridge, and the device
# have reached the bounded ready condition. This script never applies a
# configuration, starts acquisition, or produces a Burst.

set -eu

usage() {
    printf '%s\n' \
        'Usage: ./scripts/start-jetson.sh --confirm-external-vpwr-7v' \
        '' \
        'The confirmation means that the operator checked the external 7 V' \
        'supply and pressed S3 RST after the supply became stable.'
}

fail() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 1
}

confirmed=0
for argument in "$@"; do
    case "$argument" in
        --confirm-external-vpwr-7v) confirmed=1 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; fail "unknown argument: $argument" ;;
    esac
done

[ "$confirmed" -eq 1 ] || fail \
    'refusing real-device startup without --confirm-external-vpwr-7v'

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repository_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
compose_file="$repository_root/deploy/compose.jetson.yaml"
docker_bin=${USAC_DOCKER_BIN:-docker}
curl_bin=${USAC_CURL_BIN:-curl}
ready_timeout=${USAC_READY_TIMEOUT_SECONDS:-30}
poll_seconds=${USAC_READY_POLL_SECONDS:-1}
web_url=${USAC_WEB_URL:-http://127.0.0.1:8000/}
core_data_dir=${USAC_CORE_DATA_DIR:-/var/lib/tuss4470/core}
spool_dir=${USAC_BRIDGE_SPOOL_DIR:-/var/lib/tuss4470/bridge/spool}
launcher_log_dir=${USAC_LAUNCHER_LOG_DIR:-/var/lib/tuss4470/launcher}

command -v "$docker_bin" >/dev/null 2>&1 || fail "Docker was not found: $docker_bin"
command -v "$curl_bin" >/dev/null 2>&1 || fail "curl was not found: $curl_bin"
"$docker_bin" compose version >/dev/null 2>&1 || fail 'Docker Compose is unavailable'
[ -f "$compose_file" ] || fail "Compose file not found: $compose_file"

if [ -n "${USAC_SERIAL_DEVICE:-}" ]; then
    serial_device=$USAC_SERIAL_DEVICE
else
    set -- /dev/serial/by-id/usb-Texas_Instruments_MSP430-USB_Example_*-if00
    [ -e "$1" ] || fail \
        'TUSS4470 USB CDC device was not found under /dev/serial/by-id'
    [ "$#" -eq 1 ] || fail \
        'multiple TUSS4470 USB CDC devices found; set USAC_SERIAL_DEVICE explicitly'
    serial_device=$1
fi
[ -e "$serial_device" ] || fail "serial device does not exist: $serial_device"

mkdir -p "$core_data_dir" "$spool_dir" "$launcher_log_dir" || fail \
    'could not create the configured persistent or launcher log directories'
[ -w "$core_data_dir" ] || fail "core data directory is not writable: $core_data_dir"
[ -w "$spool_dir" ] || fail "bridge spool directory is not writable: $spool_dir"
[ -w "$launcher_log_dir" ] || fail "launcher log directory is not writable: $launcher_log_dir"

export USAC_CORE_IMAGE=${USAC_CORE_IMAGE:-tuss4470-acquisition-core:1.0.1}
export USAC_SERIAL_DEVICE=$serial_device
export USAC_CORE_DATA_DIR=$core_data_dir
export USAC_BRIDGE_SPOOL_DIR=$spool_dir

cd "$repository_root"

write_diagnostic_log() {
    reason=$1
    observation=$2
    diagnostic_file="$launcher_log_dir/start-failure-$(date +%Y%m%d-%H%M%S).log"
    {
        printf '%s\n' "$reason"
        printf '%s\n' "$observation"
        "$docker_bin" compose -f "$compose_file" ps 2>&1 || true
        "$docker_bin" compose -f "$compose_file" logs --no-color --tail 200 2>&1 || true
    } > "$diagnostic_file"
    printf '%s\n' "$diagnostic_file"
}

printf 'Starting Jetson Core and Bridge with device %s\n' "$serial_device"
if ! "$docker_bin" compose -f "$compose_file" up -d --no-build; then
    log_file=$(write_diagnostic_log \
        'Docker Compose could not start the Jetson services' \
        'readiness checks were not started')
    printf 'ERROR: Docker Compose could not start the Jetson services.\n' >&2
    printf 'Diagnostic log: %s\n' "$log_file" >&2
    exit 1
fi

start_seconds=$(date +%s)
ready=0
last_observation='no response received'
while [ "$(( $(date +%s) - start_seconds ))" -lt "$ready_timeout" ]; do
    health=$(
        "$curl_bin" -fsS "${web_url%/}/api/v1/health" 2>/dev/null || true
    )
    device=$(
        "$curl_bin" -fsS "${web_url%/}/api/v1/device" 2>/dev/null || true
    )
    last_observation="health=$health device=$device"
    if printf '%s' "$health" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' \
        && printf '%s' "$device" | grep -q '"connected"[[:space:]]*:[[:space:]]*true' \
        && printf '%s' "$device" | grep -q '"health"[[:space:]]*:[[:space:]]*"NORMAL"' \
        && printf '%s' "$device" | grep -q '"vdrv_ready"[[:space:]]*:[[:space:]]*1'; then
        ready=1
        break
    fi
    sleep "$poll_seconds"
done

if [ "$ready" -ne 1 ]; then
    log_file=$(write_diagnostic_log \
        "Readiness timeout after $ready_timeout seconds" \
        "$last_observation")
    printf 'ERROR: Jetson services or device did not become ready within %s seconds.\n' \
        "$ready_timeout" >&2
    printf 'Diagnostic log: %s\n' "$log_file" >&2
    exit 1
fi

printf 'Jetson services and device ready.\n'
printf 'Web console: %s\n' "$web_url"

# A desktop opener is optional: an SSH session has no graphical display, but
# service startup is still successful and the printed URL remains authoritative.
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    browser_opener=${USAC_BROWSER_OPENER:-xdg-open}
    if command -v "$browser_opener" >/dev/null 2>&1; then
        "$browser_opener" "$web_url" >/dev/null 2>&1 &
        printf 'Jetson browser open requested.\n'
    else
        printf 'No desktop URL opener found; open the Web console URL manually.\n'
    fi
else
    printf 'No Jetson desktop session detected; open the Web console URL locally.\n'
fi
