# Security build and verification

## cloudflared upgrade — 2026-10-27

cloudflared is pinned to [2026.10.3](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.3),
built with Go 1.27.3 and locked dependencies. This retains the previous SSH
dependency fix while incorporating upstream security updates. Relative to the
release locks, chi is pinned to v5.4.0 for
[CVE-2026-114437](https://github.com/advisories/GHSA-j6qf-3m9c-vwj3) and
compress to v1.18.7 for
[CVE-2026-63209](https://github.com/klauspost/compress/security/advisories/GHSA-259r-337f-4rfw).
The source archive, Go builder, and refreshed static distroless runtime remain
SHA-256 pinned. The Compose image is
`development-gateway-cloudflared:2026.10.3-security1`.

The [Cloudflare eMudhra advisory](https://blog.cloudflare.com/emudhra-certificate-compromise)
requires cloudflared 2026.10.2 or later because compromised intermediate CA
keys can allow forged certificates. For this custom build, updating the source
alone is insufficient: the Go verifier and runtime certificate trust store
are updated too. TLS verification remains enabled.

Trivy 0.76.1 with its October 27 database reports no Critical, High, Medium,
or Low findings in the upgraded cloudflared image. The Unknown OpenPGP flag
is retained; symbol inspection of the final binary found no OpenPGP code.
Evidence: [October 27 security scan](review/2026-10-27-security-scan.json).

| Image | Critical / High / Medium / Low | Unknown |
| ----- | ------------------------------ | ------- |
| `development-gateway-cloudflared:2026.10.3-security1` | 0 / 0 / 0 / 0 | 1 |
| Caddy rebuilt from unchanged pins | 0 / 9 / 23 / 2 | 2 |

Counts are package findings, including separate entries for each binary.
The new scan flags Caddy's existing Go, dependency, and CA bundle pins;
these require a separate security upgrade. The October 1 clean result no
longer represents the current advisory database. Caddy's build and its
`forward_auth` restriction remain unchanged in this cloudflared upgrade.

Validation passed all 9 development and 12 template tests using built binaries,
including the upgraded healthcheck, plus Compose validation with dummy credentials.
An offline Go verifier using the corresponding toolchains and runtime trust stores
accepted all 14 published eMudhra test chains before the upgrade and rejected
all 14 afterward. These are verifier/trust-store checks, separate from running
the cloudflared tunnel against a test origin.

## Previous image scan — 2026-10-01

The generic template builds patched Caddy and cloudflared from pinned sources
and module graphs. The exact images were scanned using Trivy 0.74.0 and its
database updated at `2026-10-01T01:24:14Z`, without vulnerability ignore rules.
Evidence: [security-scan.json](review/2026-10-01-security-scan.json).

| Image | Critical / High / Medium / Low | Remaining scanner flags |
| --- | --- | --- |
| `development-gateway-caddy:2.11.4-security1` | 0 / 0 / 0 / 0 | One Unknown OpenPGP advisory |
| `development-gateway-cloudflared:2026.9.3-security1` | 0 / 0 / 0 / 0 | One Unknown OpenPGP advisory |

Both binaries use Go 1.27.1, `CGO_ENABLED=0`, and digest-pinned static distroless
runtimes. Native curl/OpenSSL/glibc/zlib libraries from the former images are
absent. Builder images are pinned by digest; cloudflared's release archive is
verified by SHA-256. The complete module locks are under `build/`.

Caddy 2.11.4 uses updated CEL, OpenTelemetry, gRPC, and Go crypto/network/text
dependencies. CEL 0.29 requires two `NewCall` argument slices to change from
`Interpretable` to `InterpretableV2`, matching [upstream Caddy](https://github.com/caddyserver/caddy/blob/master/modules/caddyhttp/celmatcher.go).
The builder checks that exactly two release-source lines match before applying
the compatibility backport to vendored sources. The original version/checksums
remain available to binary scanners. A regression test exercises the matcher.
The Cloudflare DNS module stays at v0.2.4. cloudflared 2026.9.3 uses the patched
SSH dependency and its resulting locked module graph.

### Previous advisory assessments

**GO-2026-5932** concerns the unmaintained `golang.org/x/crypto/openpgp` package.
The scanner matches the crypto module used for other functionality. Symbol
inspection of both final unstripped binaries found no OpenPGP symbols; runtimes
contain neither package source nor a Go compiler. This is assessed as vulnerable
code not present, with the scanner flag retained in the evidence. Recheck after
dependency/feature changes. No fixed module version is published for this flag.

**GHSA-6365-7ppr-5r92** affects Caddy configurations combining `forward_auth` and
`reverse_proxy`. The template contains no `forward_auth`, and regression tests
reject adding it while this release remains pinned. The [upstream advisory](https://github.com/caddyserver/caddy/security/advisories/GHSA-6365-7ppr-5r92)
lists 2.11.5 as the fixed version. Upgrade to an available fixed stable release,
with updated locks and validation, before introducing that feature.

These assessments cover the supplied template and dated build, not arbitrary
app routes or future vulnerabilities. Review upstream advisories and repeat
scanning when upgrading; do not discard the Unknown scanner flag silently.

## Configuration protections and validation

Gateway services run as PUID/PGID with capabilities dropped and read-only root
filesystems. Binary health checks use loopback only, reject redirects, and
require 2xx. Caddy binds only its gateway address, disables packet forwarding,
and accepts public requests only from the tunnel's socket peer. Public apps must
be added explicitly; backend networks remain separate. Forwarded headers are
sanitized before proxying.

The host firewall reserves development ports across IPv4/IPv6 and every host
address, allowing only loopback or Caddy through its exact Docker bridge. Its
installer validates/applies an atomic batch, records a rollback snapshot, and
restores prior rules/units on installation failure without restarting Docker.

Validation includes both image builds/scans, Compose configuration, nonroot
Caddyfile validation inside the restricted runtime image, cloudflared's version
check, shell/systemd checks, and nftables checks/repeated loads in an isolated network
namespace. Twelve binary-backed tests cover default denials, numeric routing,
private TLS, customized example auth/allowlists, tunnel peer restrictions, HTTPS
redirects, forwarded-header sanitization, WebSockets, health checks, and CEL.
No production credentials, routes, certificate state, or host firewall changes
are needed for template tests.
