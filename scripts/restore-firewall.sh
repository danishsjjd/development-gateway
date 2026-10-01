#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ] || [ "$#" -ne 1 ] || [ ! -f "$1/prepared.nft" ]; then
    echo "Usage: sudo sh scripts/restore-firewall.sh /var/backups/development-gateway-firewall-..." >&2
    exit 1
fi
backup_dir=$1
systemctl stop caddy-gateway-firewall.service || true
systemctl disable caddy-gateway-firewall.service || true
for target in /etc/caddy-gateway.nft /etc/systemd/system/caddy-gateway-firewall.service /etc/systemd/system/docker.service.d/caddy-gateway-firewall.conf; do
    name=$(basename "$target")
    if [ -f "$backup_dir/$name.absent" ]; then
        rm -f "$target"
    else
        cp -p "$backup_dir/$name" "$target"
    fi
done
if nft list table inet caddy_gateway >/dev/null 2>&1; then
    nft delete table inet caddy_gateway
fi
if [ -f "$backup_dir/table.present" ]; then nft -f "$backup_dir/previous.nft"; fi
systemctl daemon-reload
if [ -f "$backup_dir/service.enabled" ]; then systemctl enable caddy-gateway-firewall.service; fi
if [ -f "$backup_dir/service.active" ]; then systemctl start caddy-gateway-firewall.service; fi
echo "Restored firewall configuration from $backup_dir; Docker was not restarted."
