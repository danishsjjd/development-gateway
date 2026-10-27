#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ] || [ "$#" -ne 1 ] || [ ! -f "$1/prepared.nft" ]; then
    echo "Usage: sudo sh scripts/restore-firewall.sh /var/backups/development-gateway-firewall-..." >&2
    exit 1
fi
backup_dir=$1

# Reject an incomplete snapshot before changing rules or installed files.
for target in /etc/caddy-gateway.nft /etc/systemd/system/caddy-gateway-firewall.service /etc/systemd/system/docker.service.d/caddy-gateway-firewall.conf; do
    name=$(basename "$target")
    if [ ! -f "$backup_dir/$name.absent" ] && [ ! -f "$backup_dir/$name" ]; then
        echo "Missing firewall backup: $backup_dir/$name" >&2
        exit 1
    fi
done

umask 077
restore_file=$(mktemp "$backup_dir/restore-XXXXXXXX.nft")
trap 'rm -f -- "$restore_file"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
{
    # 'add' is idempotent: also handle an already absent current table.
    # Delete and recreate in ONE transaction, so errors retain current rules.
    printf 'add table inet caddy_gateway\ndelete table inet caddy_gateway\n'
    if [ -f "$backup_dir/table.present" ]; then cat "$backup_dir/previous.nft"; fi
} > "$restore_file"
nft --check --file "$restore_file"
nft --file "$restore_file"

# Do not stop/restart this oneshot: Docker may Require it, propagating a stop.
# Restore files and boot enablement while leaving an active oneshot active.
systemctl disable caddy-gateway-firewall.service || true
for target in /etc/caddy-gateway.nft /etc/systemd/system/caddy-gateway-firewall.service /etc/systemd/system/docker.service.d/caddy-gateway-firewall.conf; do
    name=$(basename "$target")
    if [ -f "$backup_dir/$name.absent" ]; then
        rm -f "$target"
    else
        cp -p "$backup_dir/$name" "$target"
    fi
done
systemctl daemon-reload
if [ -f "$backup_dir/service.enabled" ]; then systemctl enable caddy-gateway-firewall.service; fi
if [ -f "$backup_dir/service.active" ]; then systemctl start caddy-gateway-firewall.service; fi
echo "Restored firewall configuration from $backup_dir; Docker was not restarted."
