# Development gateway

Use Caddy for development apps over Tailscale and public Docker apps through Cloudflare Tunnel.

| App                                  | Example URL                      |
| ------------------------------------ | -------------------------------- |
| Host development server on port 5173 | `https://5173.local.example.com` |
| Public Docker app                    | `https://app.example.com`        |

You need a Linux server with Docker Compose, Tailscale, and a Cloudflare-managed domain. Replace `example.com` with your domain.

## Setup

### 1. Prepare the host

Create the gateway network and let Docker bind the Tailscale IP before Tailscale starts at boot:

```bash
sudo systemctl enable --now docker.service

docker network create --driver bridge \
  --subnet 172.18.0.0/16 --ip-range 172.18.1.0/24 \
  --gateway 172.18.0.1 caddy_net

echo 'net.ipv4.ip_nonlocal_bind=1' | sudo tee /etc/sysctl.d/99-tailscale-bind.conf
sudo sysctl --system
```

### 2. Set your values and tokens

```bash
cp .env.example .env
touch .cloudflared.token
chmod 600 .env .cloudflared.token
install -d -m 700 caddy_data caddy_config
$EDITOR .env .cloudflared.token
```

- `.env`: set `MY_DOMAIN` to your domain, `TAILSCALE_IP` from `tailscale ip -4`, `PUID`/`PGID` from `id -u` / `id -g`, and `CLOUDFLARE_API_TOKEN` to a token with `Zone:Read` and `DNS:Edit` for your zone. The file contains a real secret; keep it ignored and mode `0600`.
- `.cloudflared.token`: paste the runner token from a remotely managed Cloudflare Tunnel.

Create the state directories and files as the user selected by `PUID`/`PGID`.
Caddy and cloudflared run as that user, with capabilities dropped and read-only
root filesystems. Caddy writes only to its data/config mounts and a small tmpfs.
For an existing installation, back up credentials and stopped certificate state
before changing ownership or moving its DNS token from `.env.secret` into `.env`.

### 3. Configure Cloudflare

- Add a **DNS-only A record** for `*.local.example.com` pointing to the server's Tailscale IP.
- In your tunnel, add a published application route for `*.example.com` to `http://caddy:8080`.
- Add a **proxied CNAME record** named `*` pointing to `<TUNNEL-UUID>.cfargotunnel.com`.
- Enable **SSL/TLS → Edge Certificates → Always Use HTTPS**, or another edge redirect. Caddy also redirects requests unless Cloudflare reports `X-Forwarded-Proto: https`. [Setting details](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/always-use-https/).
- Leave **HTTP Host Header** unset and visitor IP headers enabled. Caddy needs the original hostname and Cloudflare's `CF-Connecting-IP`.

### 4. Protect the gateway and development ports

Install `nftables` on the host (`sudo apt install nftables` on Ubuntu/Debian), then run:

```bash
sudo sh scripts/install-firewall.sh
```

This protects both:

- Caddy's HTTPS port: TCP and UDP traffic must come through `tailscale0`.
- Host development ports: TCP `3000–9999` is reserved across **all host addresses, IPv4 and IPv6**. Loopback remains available; only Caddy (`172.18.0.2`) on the exact `caddy_net` bridge can reach `172.18.0.1` through these ports.

It loads before Docker at boot; Docker will not start if the firewall service fails.
The installer discovers the existing bridge, validates and atomically applies
its own table, and saves prior rules/units under `/var/backups/remote-gateway-firewall-*`.
It restores that snapshot if installation fails and prints the restoration command
on success. Docker is not restarted. Keep the backup; do not flush the table when
changing other host firewall rules.

### 5. Start Caddy and the tunnel

```bash
docker compose up -d --build
docker compose ps
```

Both images are built from pinned release sources, Go dependencies, and image
digests. Caddy 2.11.4 uses patched dependencies and a checked two-line CEL
compatibility backport; cloudflared 2026.9.3 includes a patched SSH dependency.
Static distroless runtimes omit the old native libraries. See [SECURITY.md](SECURITY.md)
for dated scan results and remaining advisory assessments.

Health checks use the included `/usr/bin/healthcheck` binary; these images have
no shell or wget. Caddy checks its loopback admin API; cloudflared checks its
loopback `/ready` endpoint and becomes healthy after a tunnel is connected.
Check the intended HTTPS route as well as container health. The generic public
listener returns 404 until you explicitly add app handlers.

This template shares container names, addresses, and port bindings with other
gateway deployments. Start only one copy on a host.

## Development apps

Bind your server to `172.18.0.1` on a port from `3000` to `9999`:

```bash
npm run dev -- --host 172.18.0.1 --port 5173
```

Open `https://5173.local.example.com` from a Tailscale device. Use your app's equivalent bind option and restart any existing server with this address.

Check that `ss -lnt 'sport = :5173'` shows `172.18.0.1:5173`. From another LAN device, `http://<server-LAN-IP>:5173` should fail.

## Public Docker apps

Give each app its own network, shared only with Caddy and that app's services. Keep apps off `caddy_net` and do not publish their ports. [Docker network isolation](https://docs.docker.com/engine/network/drivers/bridge/).

```bash
docker network create --driver bridge myapp_backend
```

In the app's Compose file:

```yaml
services:
  myapp:
    image: your-image
    networks: [myapp_backend]

networks:
  myapp_backend:
    external: true
    name: myapp_backend
```

In this repo, add the network to `docker-compose.override.yml`:

```yaml
services:
  caddy:
    networks:
      myapp_backend: {}

networks:
  myapp_backend:
    external: true
    name: myapp_backend
```

Compose merges both files and keeps Caddy's fixed IP. Run `docker compose up -d` to attach the network; a reload cannot. Each app needs a different network and unique service name or alias.

In `caddy/Caddyfile`, put public handlers inside **`:8080` → `route`**, after its checks and before the fallback `handle`. Replace the hostname, service name, and port:

```caddyfile
@myapp host app.example.com
handle @myapp {
	reverse_proxy myapp:3000 {
		import app_proxy_headers
	}
}
```

Validate and reload:

```bash
docker exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Run reload only if validation succeeded. For private named apps, put handlers
inside `*.local.{$MY_DOMAIN}` before numeric development routing, using the same
header snippet and a dedicated backend. If an app trusts forwarded headers,
reserve a Caddy address on that backend and trust only that address.

Do not add `forward_auth` with the pinned Caddy release; see SECURITY.md for the
upstream advisory. The default configuration does not use it.

## Validation and upgrades

After building, run the regression suite without starting the Compose stack:

```bash
sh scripts/test-gateway.sh
```

This extracts the Caddy/healthcheck binaries from the built image and uses
loopback, temporary TLS/state, dummy credentials, and mock apps. It checks the
unmodified template's default denials and customized example handlers, including
authentication, forwarded headers, WebSockets, numeric routing, and CEL.
Requirements: Docker and Python 3.9 or newer on a Linux host.

Build inputs live in `Dockerfile`, `Dockerfile.cloudflared`, and `build/`.
When upgrading, review upstream release/advisory changes, update source checksums
and module locks deliberately, build and scan both images, and run the suite.
Retain image digest pins. A dated clean scan does not guarantee future releases
or customized app configurations are free of vulnerabilities.
