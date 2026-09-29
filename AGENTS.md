# Generic gateway template

The `main` branch is the reusable template. Check Git status before editing.
Keep this template free of personal domains, app routes, credentials, copied
certificate state, and machine-specific migration/backup paths.

Preserve the pinned security build inputs and fail-closed public defaults.
Do not add `forward_auth` until the upstream Caddy advisory is fixed in the
pinned release; see SECURITY.md. Keep real `.env`, tunnel tokens, and runtime
state ignored and outside the Docker build context.

Tests use dummy credentials, loopback, temporary TLS/state, and the built
binaries; see README.md. Do not run `docker compose up` or the firewall installer
on a host just to test the template: another deployed gateway may already use
the same names/addresses. Build images under this checkout's distinct tags and
use isolated validation containers without ports or production state.
