# Development gateway

Open a host development server at `https://<port>.local.example.com` over
Tailscale. Ports **3000–9999** work automatically: no Caddyfile edits per project.
Caddy is the only service started by default. [Public apps](docs/public-apps.md)
through Cloudflare Tunnel are optional.

You need Linux, Docker Compose, Tailscale, nftables, and a Cloudflare-managed
domain. Replace `example.com` with your domain. Run commands from this directory.
Only one gateway can use this host's shared names, addresses, and ports.

## One-time setup

### 1. Prepare the network

On a fresh host:

```bash
sudo systemctl enable --now docker.service

docker network create --driver bridge \
  --subnet 172.18.0.0/16 --ip-range 172.18.1.0/24 \
  --gateway 172.18.0.1 caddy_net

echo 'net.ipv4.ip_nonlocal_bind=1' | sudo tee /etc/sysctl.d/99-tailscale-bind.conf
sudo sysctl --system
```

Keep an existing `caddy_net`; do not recreate it. The sysctl lets Docker bind
Tailscale's IP before Tailscale starts at boot.

### 2. Set your domain and DNS token

```bash
umask 077
cp .env.example .env
chmod 600 .env
install -d -m 700 caddy_data caddy_config
$EDITOR .env
```

| Setting | Value |
| --- | --- |
| `MY_DOMAIN` | Your Cloudflare-managed domain |
| `TAILSCALE_IP` | Output of `tailscale ip -4` |
| `PUID` / `PGID` | Output of `id -u` / `id -g` |
| `CLOUDFLARE_API_TOKEN` | Token with **Zone:Read** and **DNS:Edit** for this zone |

Create these files/directories as the selected user. Keep `.env` private and
ignored. The DNS token lets Caddy obtain wildcard HTTPS certificates, including
for private development; a tunnel token is only needed for public apps.

In Cloudflare DNS, add a **DNS-only A record** for `*.local.example.com` pointing
to the server's Tailscale IP.

### 3. Keep the host firewall protection

If the gateway's firewall is already installed, keep it. On a fresh host,
install nftables (`sudo apt install nftables` on Debian/Ubuntu), then run:

```bash
sudo sh scripts/install-firewall.sh
```

It limits gateway HTTPS to Tailscale and reserves TCP ports 3000–9999 across all
host addresses, IPv4 and IPv6. Only loopback and Caddy through its exact bridge
can reach development servers. Docker startup depends on these rules.
Keep the installer's backup and printed restore command; do not flush its table.
[Firewall and recovery details](docs/maintenance.md#firewall).

### 4. Start Caddy

```bash
docker compose up -d --build
docker compose ps
```

The first build compiles Caddy with Cloudflare DNS support and pinned fixes.
Daily development does not need a rebuild or a security review.

## Daily development

Bind your server to `172.18.0.1` on a port from 3000 to 9999:

```bash
npm run dev -- --host 172.18.0.1 --port 5173
```

Open **`https://5173.local.example.com`** from a Tailscale device. Use your app's
equivalent bind option; restart an existing server to change its bind address.
If the app checks hostnames, allow `5173.local.example.com` in its settings.

If it fails, check `docker compose ps`, `docker compose logs --tail=50 caddy`,
and `ss -lnt 'sport = :5173'` (expect `172.18.0.1:5173`). Direct access from
another LAN device to `http://<server-LAN-IP>:5173` should fail.

For named private or public Docker apps, see [app routing](docs/public-apps.md#add-an-app).
For config reloads, state, tests, and image upgrades, see [maintenance](docs/maintenance.md).
Build pins and dated security findings remain in [SECURITY.md](SECURITY.md).
