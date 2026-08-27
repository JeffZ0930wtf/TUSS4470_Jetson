#!/usr/bin/env sh
# Creates the checkout-local Jetson/Linux environment from uv.lock. The script
# deliberately avoids the host-wide base environment used for generic tools.
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_root"

if command -v uv >/dev/null 2>&1; then
    uv_executable=$(command -v uv)
elif [ -x .tools/uv/uv ]; then
    uv_executable="$repository_root/.tools/uv/uv"
else
    printf '%s\n' \
        'uv is required but was not found on PATH.' \
        'Install uv 0.12.5 from the official Astral release:' \
        'https://github.com/astral-sh/uv/releases/tag/0.12.5' >&2
    exit 1
fi

uv_version=$($uv_executable --version)
case "$uv_version" in
    'uv 0.12.5 '*) ;;
    'uv 0.12.5') ;;
    *)
        printf 'uv 0.12.5 is required; found: %s\n' "$uv_version" >&2
        exit 1
        ;;
esac

# Reproducible equivalent: uv sync --frozen --extra dev
$uv_executable sync --frozen --extra dev

test -f .venv/bin/activate
printf '%s\n' \
    'Development environment is synchronized.' \
