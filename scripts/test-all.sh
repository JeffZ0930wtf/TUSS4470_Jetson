#!/usr/bin/env sh
# Jetson/Linux aggregate gate for host tests, protocol vectors, native ARM64
# container execution, and AMD64 OCI cross-build; no MSP430 flashing occurs.
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_root"

expected_environment="$repository_root/.venv"
if [ "${VIRTUAL_ENV:-}" != "$expected_environment" ]; then
    printf '%s\n' 'activate the repository .venv first: . .venv/bin/activate' >&2
    exit 1
fi

.venv/bin/python -m pytest
node packages/usac_runtime/tests/test_m5_app.cjs
./scripts/test-c-vectors.sh

docker build --platform linux/arm64 \
    -f deploy/Dockerfile.core \
    -t tuss4470-acquisition-core:m1-arm64 .
docker run --rm --platform linux/arm64 tuss4470-acquisition-core:m1-arm64

mkdir -p .tools/buildx
docker buildx build --platform linux/amd64 \
    --output type=oci,dest=.tools/buildx/tuss4470-acquisition-core-m1-amd64.tar \
    -f deploy/Dockerfile.core .
