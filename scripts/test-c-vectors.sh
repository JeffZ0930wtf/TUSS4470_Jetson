#!/usr/bin/env sh
# Verifies that the host C implementation consumes the same committed protocol
# vectors as Python, catching byte-order or CRC drift across platforms.
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_root"

if ! command -v cc >/dev/null 2>&1; then
    printf '%s\n' 'required host C compiler not found: cc' >&2
    exit 1
fi

mkdir -p .tools/c-tests
cc -std=c11 -Wall -Wextra -Werror \
    tests/c/test_protocol_vectors.c \
    -o .tools/c-tests/test_protocol_vectors
.tools/c-tests/test_protocol_vectors
