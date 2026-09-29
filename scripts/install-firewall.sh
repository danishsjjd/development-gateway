#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo on the Linux Docker host." >&2
    exit 1
fi

for command in nft systemctl docker; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Install $command on the Linux Docker host first." >&2
        exit 1
    fi
done

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

# Use the exact existing bridge, rather than trusting a source IP arriving
# through any app network. Inspect only networking metadata, never secrets.
bridge=$(docker network inspect caddy_net --format '{{index .Options "com.docker.network.bridge.name"}}')
if [ -z "$bridge" ]; then
    network_id=$(docker network inspect caddy_net --format '{{.Id}}')
    bridge="br-$(printf '%s' "$network_id" | cut -c 1-12)"
fi
case "$bridge" in
    ''|*[!a-zA-Z0-9_.-]*) echo "Invalid Docker bridge interface name." >&2; exit 1 ;;
esac

mkdir -p /var/backups
backup_dir=$(mktemp -d /var/backups/remote-gateway-firewall-XXXXXXXX)
chmod 700 "$backup_dir"
for target in /etc/caddy-gateway.nft /etc/systemd/system/caddy-gateway-firewall.service /etc/systemd/system/docker.service.d/caddy-gateway-firewall.conf; do
    name=$(basename "$target")
    if [ -e "$target" ]; then cp -p "$target" "$backup_dir/$name"; else touch "$backup_dir/$name.absent"; fi
done
if nft list table inet caddy_gateway > "$backup_dir/previous.nft" 2>/dev/null; then
    touch "$backup_dir/table.present"
fi
if systemctl is-enabled --quiet caddy-gateway-firewall.service 2>/dev/null; then
    touch "$backup_dir/service.enabled"
fi
if systemctl is-active --quiet caddy-gateway-firewall.service; then
    touch "$backup_dir/service.active"
fi

sed "s/^define caddy_bridge = .*/define caddy_bridge = \"$bridge\"/" "$repo_dir/firewall/caddy-gateway.nft" > "$backup_dir/prepared.nft"
# Check and apply the rules before making Docker depend on the service. nft
# applies the batch atomically. Failed later installation restores the snapshot.
nft --check --file "$backup_dir/prepared.nft"
rollback() {
    code=$?
    trap - EXIT
    if [ "$code" -ne 0 ]; then
        echo "Firewall installation failed; restoring $backup_dir." >&2
        sh "$repo_dir/scripts/restore-firewall.sh" "$backup_dir" || echo "Automatic restoration failed; use the backup path above." >&2
    fi
    exit "$code"
}
trap rollback EXIT
nft --file "$backup_dir/prepared.nft"
install -m 644 "$backup_dir/prepared.nft" /etc/caddy-gateway.nft
install -m 644 "$repo_dir/firewall/caddy-gateway-firewall.service" /etc/systemd/system/caddy-gateway-firewall.service
install -D -m 644 "$repo_dir/firewall/docker-firewall.conf" /etc/systemd/system/docker.service.d/caddy-gateway-firewall.conf
systemctl daemon-reload
systemctl enable caddy-gateway-firewall.service
# Reload also reapplies the rules when this installer is run again.
systemctl reload-or-restart caddy-gateway-firewall.service
nft list table inet caddy_gateway
trap - EXIT
echo "Firewall installed; rollback: sudo sh $repo_dir/scripts/restore-firewall.sh $backup_dir"
