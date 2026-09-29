#!/bin/sh
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
umask 077
test_dir=$(mktemp -d)
test_container=''
cleanup() {
    if [ -n "$test_container" ]; then docker rm "$test_container" >/dev/null; fi
    rm -rf -- "$test_dir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Create without starting: no network access, host ports, credentials, or live state.
test_container=$(docker create --network none development-gateway-caddy:2.11.4-security1)
docker cp "$test_container:/usr/bin/caddy" "$test_dir/caddy"
docker cp "$test_container:/usr/bin/healthcheck" "$test_dir/healthcheck"
cd "$repo_dir"
CADDY_BINARY="$test_dir/caddy" HEALTHCHECK_BINARY="$test_dir/healthcheck" \
    python3 -m unittest discover -s tests -v
