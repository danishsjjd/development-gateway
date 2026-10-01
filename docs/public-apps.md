# Public apps (optional)

Finish the [private setup](../README.md) first. For a named private Docker app,
skip tunnel setup and go to [Add an app](#add-an-app). Public apps must provide
their own login or API-key checks; adding a public route exposes that app to
the internet.

## Tunnel setup

Create a remotely managed Cloudflare Tunnel, then save its runner token:

```bash
umask 077
touch .cloudflared.token
chmod 600 .cloudflared.token
$EDITOR .cloudflared.token
```

Paste only the token into the file. Keep it ignored; Compose mounts it read-only.

In Cloudflare:

- Publish `*.example.com` through the tunnel to `http://caddy:8080`.
- Add a **proxied CNAME** named `*` pointing to `<TUNNEL-UUID>.cfargotunnel.com`.
- Enable **SSL/TLS → Edge Certificates → Always Use HTTPS**, or an equivalent
  edge redirect. Caddy also redirects unless Cloudflare reports
  `X-Forwarded-Proto: https`. [Cloudflare instructions](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/always-use-https/).
- Leave **HTTP Host Header** unset and visitor IP headers enabled. Caddy needs
  the original hostname and `CF-Connecting-IP`.

Start the tunnel alongside Caddy:

```bash
docker compose --profile public up -d --build
docker compose --profile public ps
```

The public listener returns 404 until you add a handler below. Only the tunnel's
socket peer (`172.18.0.3`) may use it; visitor-supplied IP headers cannot bypass
this check. Caddy also normalizes forwarded headers before sending them to apps.
A host firewall cannot replace these HTTP checks.

Use `--profile public` for stack-wide commands that should include the tunnel.
Alternatively, set `COMPOSE_PROFILES=public` in `.env` to enable it by default.
Running plain `docker compose up -d` later does not stop an existing tunnel.
To stop public access explicitly:

```bash
docker compose --profile public stop cloudflared
```

## Add an app

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

In this repo, add the network to the ignored `docker-compose.override.yml`:

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

Compose merges both files and keeps Caddy's fixed IP. Run `docker compose up -d`
to attach the network; include `--profile public` if using the tunnel. A reload
cannot attach networks. Each app needs its own network and unique service name
or alias.

### Named private apps

Put a handler inside `*.local.{$MY_DOMAIN}`, before numeric development routing:

```caddyfile
@myapp host app.local.{$MY_DOMAIN}
handle @myapp {
	reverse_proxy myapp:3000 {
		import app_proxy_headers
	}
}
```

This route needs no tunnel. If the app trusts forwarded headers, reserve a Caddy
address on that backend and trust only that address. Validate and reload using
the commands below.

### Public apps

In [`caddy/Caddyfile`](../caddy/Caddyfile), put public handlers inside **`:8080` → `route`**, after its checks and before the fallback `handle`. Replace the hostname, service name, and port:

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

Run reload only if validation succeeded.

Do not add `forward_auth` with the pinned Caddy release; see [SECURITY.md](../SECURITY.md) for the
upstream advisory. The default configuration does not use it.
