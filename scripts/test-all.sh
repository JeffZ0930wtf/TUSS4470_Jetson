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
node packages/usac_runtime/tests/test_web_app.cjs
./scripts/test-c-vectors.sh

candidate_sha=$(git rev-parse --verify HEAD)
arm64_image="tuss4470-acquisition-core:1.0.0-${candidate_sha}-arm64"
amd64_oci=".tools/buildx/tuss4470-acquisition-core-1.0.0-${candidate_sha}-amd64.oci.tar"

docker build --platform linux/arm64 \
    --build-arg VERSION=1.0.0 \
    --build-arg VCS_REF="$candidate_sha" \
    -f deploy/Dockerfile.core \
    -t "$arm64_image" .
docker run --rm --platform linux/arm64 --entrypoint python "$arm64_image" -c \
    'from usac_protocol.frame import Frame, MessageType, decode_frame, encode_frame; raw = encode_frame(Frame(MessageType.GET_STATUS, 1, b"")); assert decode_frame(raw).message_type is MessageType.GET_STATUS'

mkdir -p .tools/buildx
docker buildx build --platform linux/amd64 \
    --build-arg VERSION=1.0.0 \
    --build-arg VCS_REF="$candidate_sha" \
    --output "type=oci,dest=$amd64_oci" \
    -f deploy/Dockerfile.core .
