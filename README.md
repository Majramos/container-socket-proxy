# container-socket-proxy

<div align="center">

![Python Badge](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=fff&style=flat)
![Gitlab Pipeline Status](https://gitlab.com/majramos/container-socket-proxy/badges/main/pipeline.svg)
![Gitlab Release](https://gitlab.com/majramos/container-socket-proxy/-/badges/release.svg)
![Gitlab Coverage](https://gitlab.com/majramos/container-socket-proxy/badges/main/coverage.svg)

</div>

# container-socket-proxy

A dependency-free HTTP proxy that sits in front of a Podman or Docker socket and only forwards + rewrites allowed container groups. Clients talk the Podman/Docker HTTP API to the proxy; anything not enabled answers `403`.

Typical use: give CI jobs, dashboards, or monitoring agents limited (often read-only) access to Podman or Docker without handing them the full control socket.

Threat model: the proxy gates the API surface exposed through it. Whoever controls the proxy container's environment (or can start it + sibling container with different toggles) can enable anything, so treat it as an access-control convenience layer, not a security boundary against an operator.

Full usage guide and examples (podman run, quadlets, Homepage, Portainer): see
docs/docs/.

## Configuration

All configuration is via environment variables. Endpoint groups are denied by default; `ALLOW_PING` is the only group enabled by default (it powers the image `HEALTHCHECK`).

| Variable | Default | Effect |
|---|---:|---|
| `ALLOW_PING` | `1` | `/ping` health endpoints |
| `ALLOW_VERSION` | `0` | `GET /version` |
| `ALLOW_INFO` | `0` | `GET /info`, `/system/info` |
| `ALLOW_CONTAINERS` | `0` | `/containers`, `/libpod/containers/*`, `/libpod/containers/*` |
| `ALLOW_IMAGES` | `0` | `/images/*`, `/libpod/images/*` |
| `ALLOW_VOLUMES` | `0` | `/volumes/*` |
| `ALLOW_NETWORKS` | `0` | `/networks/*`, `/libpod/networks/*` |
| `ALLOW_PODS` | `0` | `/libpod/pods/*` |
| `ALLOW_EVENTS` | `0` | `/events` |
| `ALLOW_SYSTEM` | `0` | `/system` (`/prune`, `/auth`) |
| `ALLOW_EXEC` | `0` | `/exec`, `/containers/*/exec` |
| `ALLOW_BUILDS` | `0` | `/build` |
| `ALLOW_ARCHIVE` | `0` | `/containers/{id}/archive` (file copy in/out of containers) |
| `ALLOW_WRITE` | `0` | Gate for `POST/PUT/PATCH/DELETE`; without it the proxy is read-only, even in enabled groups |
| `PROXY_HOST` | `0.0.0.0` | Listen address |
| `PROXY_PORT` | `2026` | Listen port |
| `CONTAINER_SOCKET` | `/run/podman/podman.sock` | Upstream filesystem path, or `http://` / `tcp://` / `unix://` URL |
| `DOCKER_SOCKET` | `1` | Alias for `CONTAINER_SOCKET`; ignored when `CONTAINER_SOCKET` is set |
| `UPSTREAM_TIMEOUT` | `10` | Seconds allowed for upstream connect/response headers; `0` disables |
| `MAX_BODY_BYTES` | `(unlimited)` | Reject larger request bodies with `413` |
| `LOG_LEVEL` | `INFO` | `stdout` log level |

Paths match Docker-compat (`/v1.41/...`, optionally unversioned) and native `/libpod/...`. Options are checked after path normalization.

`ALLOW_ARCHIVE` and `ALLOW_EXEC` “take precedence over” `ALLOW_CONTAINERS`.

## Build

```sh
podman build -t container-socket-proxy .
```

`make image` builds the same tag and uses whichever of `podman` or `docker` is installed (`make image CONTAINER_CLI=docker` to pick explicitly).

## Run

### Rootful socket

```sh
podman run -d --name=container-socket-proxy --restart=unless-stopped \
  -p 127.0.0.1:2026:2026 \
  -v /run/podman/podman.sock:/run/podman/podman.sock \
  -e ALLOW_CONTAINERS=1 -e ALLOW_IMAGES=1 \
  container-socket-proxy
```

### Rootless socket

```sh
podman run -d --name=container-socket-proxy --restart=unless-stopped \
  -p 127.0.0.1:2026:2026 \
  --user "$(id -u):$(id -g)" \
  -v /run/user/$(id -u)/podman/podman.sock:/run/user/$(id -u)/podman/podman.sock \
  -e ALLOW_CONTAINERS=1 \
  container-socket-proxy
```

The image runs as root by default so it can reach root-owned sockets; pass `--user` matching the socket owner for rootless setups.

### Docker-backed

The same image fronts a Docker daemon — point the upstream at the Docker socket instead:

```sh
podman run -d --name=container-socket-proxy --restart=unless-stopped \
  -p 127.0.0.1:2026:2026 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e CONTAINER_SOCKET=/var/run/docker.sock \
  -e ALLOW_CONTAINERS=1 -e ALLOW_IMAGES=1 \
  container-socket-proxy
```

Connect with the Docker CLI as usual: `DOCKER_HOST=http://127.0.0.1:2026 docker ps`. Podman-native groups (`ALLOW_PODS`, `all`, `/libpod/...` paths) match nothing on Docker and can stay off.

## Use

The examples assume `-p 127.0.0.1:2026:2026`; map the host side to any port you like, e.g.
-p 127.0.0.1:9080:2026

```sh
podman --remote --url http://127.0.0.1:2026 ps
DOCKER_HOST=http://127.0.0.1:2026 docker ps
curl http://127.0.0.1:2026/ping
```

Streaming endpoints (`/events`, `/logs?follow=1`, image-pull progress) are relayed incrementally. Responses are close-delimited (`Connection: close`); there is no keep-alive.

## Limitations

- Hijacked connections (Docker-compat raw-TCP upgrades: `exec .../start`, `attach`, `/ws`) are rejected with `501`; `ALLOW_EXEC=1` is rejected for compat clients; Podman-native `/exec/attach` uses plan-chunked HTTP and streams through the proxy.
- Requests carrying an `Upgrade` header always return `501`, regardless of toggles.
- `UPSTREAM_TIMEOUT` covers connecting and waiting for response headers only. Once headers arrive, the body is relayed with no upstream timeout (streaming endpoints like `/events` idle legitimately), so a stalled upstream pins one handler thread.
- macOS: `podman-build` / `run` execute inside the Podman VM, so `/run/podman/podman.sock` resolves inside the VM. To run the proxy directly on the macOS host, point `CONTAINER_SOCKET` at `$XDG_RUNTIME_DIR/podman/podman.sock`.

## Development

```sh
uv run main.py
