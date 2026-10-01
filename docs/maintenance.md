# Maintenance

## Config changes

For routing edits, validate first and reload only if validation succeeds:

```bash
docker exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Caddy mounts the whole `caddy/` directory so editor saves through file renames
remain visible. Environment or network changes need `docker compose up -d`;
image changes also need `--build`. Add `--profile public` if using the tunnel.
A restart alone does not apply new environment or network settings.

## State and health

`caddy_data/` contains certificates/private keys; `caddy_config/` contains saved
configuration. Both are ignored, as are `.env` and `.cloudflared.token`.
Local app networks in `docker-compose.override.yml` are ignored too.
The Docker build context allows only Dockerfiles and `build/` inputs.

Services run as `PUID`/`PGID` with dropped capabilities and read-only root
filesystems. Caddy writes to its state mounts and a small tmpfs. Keep state
owned by the selected user. For an existing installation, back up credentials
and stopped certificate state before moving files, changing ownership, or
moving a DNS token from `.env.secret` into `.env`.

The images have no shell or wget. Their `/usr/bin/healthcheck` checks Caddy's
loopback admin API and cloudflared's loopback `/ready` endpoint. The tunnel
becomes healthy only after a connection is established. Check your actual
HTTPS route too; container health alone does not prove app access works.

## Firewall

The gateway rules protect TCP/UDP HTTPS through `tailscale0` and reserve TCP
3000–9999 on every host address (IPv4 and IPv6). Loopback stays available.
Only Caddy (`172.18.0.2`) through the exact `caddy_net` bridge may reach host
apps at `172.18.0.1`. Backend apps cannot use Caddy as a packet router.

The installer discovers the bridge, validates and atomically loads only its
own nftables table, and saves prior rules/units under
`/var/backups/remote-gateway-firewall-*`. It restores that snapshot on failure
and prints the restore command on success. It does not restart Docker.

Rules load before Docker at boot. If the firewall service fails, Docker will
not start. Keep the backup; use the printed restore command to undo the
installation. Do not flush the gateway table when changing other rules.
An existing firewall must enforce these same boundaries to replace this setup.

## Tests

Build and test without starting the Compose stack:

```bash
docker compose build caddy
sh scripts/test-gateway.sh
```

The script extracts Caddy and healthcheck binaries from the built template
image. Tests use loopback, temporary TLS/state, dummy credentials, and mock
apps. They cover default denials, numeric routing, private TLS, example public
allowlists/authentication, tunnel-peer checks, HTTPS redirects, forwarded
headers, WebSockets, health checks, and the patched CEL matcher.
You need Docker and Python 3.9 or newer on Linux.

Do not start this template or run the firewall installer just to test it on a
host with a deployed gateway. Use isolated validation containers without host
ports or production state. Build under this checkout's `development-gateway-*`
tags; deployed stacks may use other tags.

## Image upgrades

The custom Caddy build includes the Cloudflare DNS module for wildcard
certificates. Both images use pinned releases, Go dependency locks, and image
digests; this work is for image upgrades, not daily development.

Caddy 2.11.4 includes patched dependencies and a checked two-line CEL
compatibility backport. cloudflared 2026.9.3 includes a patched SSH dependency.
Static distroless runtimes omit the old native libraries. Dated scan results
and remaining advisory assessments are in [SECURITY.md](../SECURITY.md).

Build inputs live in `Dockerfile`, `Dockerfile.cloudflared`, and `build/`.
On an upgrade, review upstream releases/advisories, update source checksums and
module locks deliberately, retain digest pins, build/scan both images, and run
the tests. A dated clean scan cannot guarantee future versions or custom app
configurations are free of vulnerabilities.

Do not add `forward_auth` with the pinned Caddy release; see the upstream
advisory assessment in [SECURITY.md](../SECURITY.md).
