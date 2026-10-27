FROM golang:1.27.3-alpine3.23@sha256:8a5046497cda39860b832ffdbe8dd66018a0f05bb01352f533a36e7e2ced66a0 AS builder
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
WORKDIR /src
COPY build/caddy/go.mod build/caddy/go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY build/caddy/main.go ./
# Caddy 2.11.7 includes the upstream CEL compatibility and proxy fixes.
COPY build/healthcheck/main.go /healthcheck/main.go
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go build -mod=readonly -trimpath -o /out/caddy . && \
    go build -trimpath -o /out/healthcheck /healthcheck/main.go

# Both binaries are static; no curl, OpenSSL, glibc, or shell is needed.
FROM gcr.io/distroless/static-debian13:nonroot@sha256:18f4cc26c9ffa7f20a359298be7deadac5c607c8e03a02b8119f1a5fc2f82c99
ENV XDG_CONFIG_HOME=/config XDG_DATA_HOME=/data HOME=/data
WORKDIR /data
COPY --from=builder /out/caddy /usr/bin/caddy
COPY --from=builder /out/healthcheck /usr/bin/healthcheck
USER 1000:1000
ENTRYPOINT ["/usr/bin/caddy"]
CMD ["run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
