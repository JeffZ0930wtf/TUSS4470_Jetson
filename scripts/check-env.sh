#!/usr/bin/env sh
# Reports Jetson/Linux compiler, container, Python, and USB CDC prerequisites;
# it is a read-only environment gate and does not start acquisition services.
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
missing=0

report() {
    name=$1
    required=$2
    path=$3
    version=$4
    if [ -n "$path" ]; then
        printf '%-20s required=%-5s available=true  version=%s path=%s\n' \
            "$name" "$required" "$version" "$path"
    else
        printf '%-20s required=%-5s available=false\n' "$name" "$required"
        if [ "$required" = true ]; then missing=1; fi
    fi
}

git_path=$(command -v git 2>/dev/null || true)
git_version=$(${git_path:-false} --version 2>/dev/null || true)
report git true "$git_path" "$git_version"

python_path="$repository_root/.venv/bin/python"
if [ -x "$python_path" ]; then
    python_version=$($python_path --version 2>&1)
else
    python_path=
    python_version=
fi
report project-python true "$python_path" "$python_version"

if command -v uv >/dev/null 2>&1; then
    uv_path=$(command -v uv)
    uv_version=$(uv --version)
elif [ -x "$repository_root/.tools/uv/uv" ]; then
    uv_path="$repository_root/.tools/uv/uv"
    uv_version=$($uv_path --version)
else
    uv_path=
    uv_version=
fi
report uv true "$uv_path" "$uv_version"

docker_path=$(command -v docker 2>/dev/null || true)
docker_version=$(${docker_path:-false} --version 2>/dev/null || true)
report docker true "$docker_path" "$docker_version"

if [ -n "$docker_path" ]; then
    compose_version=$(docker compose version 2>/dev/null || true)
    buildx_version=$(docker buildx version 2>/dev/null || true)
else
    compose_version=
    buildx_version=
fi
report docker-compose true "$docker_path" "$compose_version"
report docker-buildx true "$docker_path" "$buildx_version"

compiler_path=$(command -v msp430-elf-gcc 2>/dev/null || true)
compiler_version=$(${compiler_path:-false} --version 2>/dev/null | head -n 1 || true)
report msp430-elf-gcc false "$compiler_path" "$compiler_version"

exit "$missing"
