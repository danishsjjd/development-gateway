FROM golang:1.27.1-alpine3.23@sha256:0908ac9b9319e09d7c238aabe914e0395c51d63c4e3d0ae8c554fda9158a5769 AS builder
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
WORKDIR /src
COPY build/caddy/go.mod build/caddy/go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY build/caddy/main.go ./
# cel-go 0.29 fixes GHSA-gcjh-h69q-9w9g but renames this call interface.
# Backport the two matching changes from upstream Caddy's celmatcher.go.
# Vendor verified release sources in the builder, then apply the small patch.
# The original module version/checksums remain available to binary scanners.
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod vendor && \
    test "$(grep -Fc '[]interpreter.Interpretable{reqAttr}' vendor/github.com/caddyserver/caddy/v2/modules/caddyhttp/celmatcher.go)" = 2 && \
    sed 's/\[\]interpreter.Interpretable{reqAttr}/[]interpreter.InterpretableV2{reqAttr}/g' \
      vendor/github.com/caddyserver/caddy/v2/modules/caddyhttp/celmatcher.go > /tmp/celmatcher.go && \
    mv /tmp/celmatcher.go vendor/github.com/caddyserver/caddy/v2/modules/caddyhttp/celmatcher.go
COPY build/healthcheck/main.go /healthcheck/main.go
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go build -mod=vendor -trimpath -o /out/caddy . && \
    go build -trimpath -o /out/healthcheck /healthcheck/main.go

# Both binaries are static; no curl, OpenSSL, glibc, or shell is needed.
FROM gcr.io/distroless/static-debian13:nonroot@sha256:e2e927ec666bae08560abb3c55d0659eceabb657f56b6782ab500a9fc7f555e3
ENV XDG_CONFIG_HOME=/config XDG_DATA_HOME=/data HOME=/data
WORKDIR /data
COPY --from=builder /out/caddy /usr/bin/caddy
COPY --from=builder /out/healthcheck /usr/bin/healthcheck
USER 1000:1000
ENTRYPOINT ["/usr/bin/caddy"]
CMD ["run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
