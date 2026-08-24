#!/usr/bin/env sh
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
