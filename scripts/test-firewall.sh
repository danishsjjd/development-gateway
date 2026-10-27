#!/bin/sh
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
for command in bwrap timeout prlimit nft python3; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Install $command to run the isolated firewall tests." >&2
        exit 1
    fi
done

# No host rules, services, credentials, sockets, or Docker networks are exposed.
# Root and CAP_NET_ADMIN exist only inside the new user/network namespaces.
exec env -i PATH=/usr/bin:/bin timeout 30 bwrap \
    --unshare-all --uid 0 --gid 0 --die-with-parent --new-session \
    --cap-add CAP_NET_ADMIN \
    --ro-bind /usr /usr \
    --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib /lib64 \
    --proc /proc --remount-ro /proc --dev /dev \
    --size 67108864 --tmpfs /scratch \
    --dir /scratch/etc --symlink /scratch/etc /etc --symlink /scratch /tmp \
    --ro-bind "$repo_dir/scripts/restore-firewall.sh" /repo/scripts/restore-firewall.sh \
    --ro-bind "$repo_dir/firewall/caddy-gateway.nft" /repo/firewall/caddy-gateway.nft \
    --ro-bind "$repo_dir/tests/firewall_restore.py" /repo/tests/firewall_restore.py \
    --remount-ro / --chdir /scratch --clearenv \
    --setenv PATH /usr/bin:/bin --setenv HOME /scratch --setenv TMPDIR /scratch \
    --setenv PYTHONDONTWRITEBYTECODE 1 --setenv GATEWAY_FIREWALL_TEST_SANDBOX 1 \
    -- prlimit --cpu=15 --as=536870912 --nproc=64 --fsize=4194304 --nofile=128 \
    -- python3 /repo/tests/firewall_restore.py
