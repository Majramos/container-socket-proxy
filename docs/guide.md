# Usage guide

`container-socket-proxy` is a dependency-free HTTP proxy that sits in front of a Podman or Docker socket and only forwards the endpoint groups you explicitly enable. Clients talk the Podman/Docker HTTP API to the proxy; anything not enabled answers `403`.

This guide covers day-to-day operation: prerequisites, how the access model works, the full configuration reference, and troubleshooting. For ready-to-copy deployments see [podman-run.md](podman-run.md), [homepage.md](homepage.md), and [quadlets.md](quadlets.md).

## Prerequisites

### Enable the Podman socket

The proxy connects to a Podman API socket, which is not enabled by default.

Rootful socket (`/run/podman/podman.sock`):

```sh
sudo systemctl enable --now podman.socket
```

Rootless socket (`/run/user/$(id -u)/podman/podman.sock`):

```sh
systemctl --user enable --now podman.socket
sudo loginctl enable-linger "$USER"
```

`enable-linger` makes the user manager (and with it the socket) start at boot instead of at first login.

Confirm where the socket lives:

```sh
podman info --format '{{.Host.Socket.Path}}'
```

### Use the Docker socket instead

The proxy works the same against a Docker daemon: set `CONTAINER_SOCKET` to the Docker socket path (conventionally `/var/run/docker.sock`) and mount it into the container. `DOCKER_SOCKET` is accepted as an alias and is ignored when `CONTAINER_SOCKET` is set. Podman-native groups (`ALLOW_PODS`, all `/libpod/...` paths) match nothing on Docker and can stay off.

### Build the image

From the repository root:

```sh
podman build -t container-socket-proxy .
```

## How it works

1. The proxy listens on plain HTTP (`PROXY_HOST:PROXY_PORT`).
2. Every request path is matched against a fixed set of endpoint groups (containers, images, volumes, ...). Paths matching no group are denied.
3. If the request's group is enabled with its `ALLOW_*` variable, the request is relayed to the upstream socket and the response streamed back.
4. Everything else answers `403` with the reason in the body.

Two properties do most of the work:

- **Default deny.** Only `ALLOW_PING` is on by default (it powers the image's `HEALTHCHECK`). Every other group must be enabled explicitly.
- **`ALLOW_WRITE` gate.** `POST`, `PUT`, `PATCH`, and `DELETE` are denied unless `ALLOW_WRITE=1`, even inside enabled groups. Without it the proxy is read-only.

Path matching accepts Docker-compatible forms (`/v1.41/...` or unversioned `/containers/...`) and native Podman forms (`/libpod/...`, optionally versioned). `ALLOW_ARCHIVE` and `ALLOW_EXEC` take precedence over `ALLOW_CONTAINERS`: the `/containers/{id}/archive` and `/containers/{id}/exec` paths belong to their own groups, so enabling `ALLOW_CONTAINERS` alone does not expose them.

Responses are close-delimited (`Connection: close`); there is no keep-alive. Streaming endpoints (`/events`, `logs?follow=1`, image pull progress) are relayed incrementally.

### Response codes

| Code | Meaning |
|---|---|
| `200` etc. | Relayed from Podman |
| `400` | Malformed request body (bad `Content-Length` or chunked framing) |
| `403` | Group not enabled, or write method without `ALLOW_WRITE`; reason in body |
| `413` | Request body larger than `MAX_BODY_BYTES` |
| `501` | Hijacked connections: any request with an `Upgrade` header, notably Docker-compat `exec.../start`, `attach`, `attach/ws` |
| `502` | Upstream unreachable: wrong `CONTAINER_SOCKET`, socket not activated, permission denied |

## Configuration reference

All configuration is via environment variables. Boolean variables accept `1`, `true`, `yes`, `on` (case-insensitive); anything else is false.

### Endpoint groups

| Variable | Default | Effect |
|---|---|---|
| `ALLOW_PING` | `1` | `/_ping`, `/libpod/_ping` health endpoints |
| `ALLOW_VERSION` | `0` | `GET /version` |
| `ALLOW_INFO` | `0` | `GET /info`, `/system/info` |
| `ALLOW_CONTAINERS` | `0` | `/containers/*`, `/libpod/containers/*` |
| `ALLOW_IMAGES` | `0` | `/images/*`, `/libpod/images/*` |
| `ALLOW_VOLUMES` | `0` | `/volumes/*`, `/libpod/volumes/*` |
| `ALLOW_NETWORKS` | `0` | `/networks/*`, `/libpod/networks/*` |
| `ALLOW_PODS` | `0` | `/libpod/pods/*` (native API only) |
| `ALLOW_EVENTS` | `0` | `/events`, `/libpod/events` |
| `ALLOW_SYSTEM` | `0` | `/system/*` (prune, df), `/auth` |
| `ALLOW_EXEC` | `0` | `/exec/*`, `/containers/{id}/exec` |
| `ALLOW_BUILD` | `0` | `/build` |
| `ALLOW_ARCHIVE` | `0` | `/containers/{id}/archive` (file copy in/out of containers) |
| `ALLOW_WRITE` | `0` | Gate for `POST/PUT/PATCH/DELETE`. Without it the proxy is read-only even in enabled groups |

### Server settings

| Variable | Default | Effect |
|---|---|---|
| `PROXY_HOST` | `0.0.0.0` | Listen address |
| `PROXY_PORT` | `2026` | Listen port (1–65535) |
| `CONTAINER_SOCKET` | `/run/podman/podman.sock` | Upstream: filesystem path, or `unix://`, `http(s)://`, `tcp://` URL |
| `DOCKER_SOCKET` | unset | Alias for `CONTAINER_SOCKET`; ignored when `CONTAINER_SOCKET` is set |
| `UPSTREAM_TIMEOUT` | `10` | Seconds allowed for upstream connect + response headers; `0` waits indefinitely |
| `MAX_BODY_BYTES` | `0` (unlimited) | Reject larger request bodies with `413` |
| `LOG_LEVEL` | `INFO` | stdlib logging level (`CRITICAL`, `ERROR`, `WARNING`/`WARN`, `INFO`, `DEBUG`) |

Invalid configuration (bad port, non-integer limit, unknown log level) makes the container exit at startup with code `2` and a message on stderr.

### Publishing under a different host port

The container always listens on `PROXY_PORT` (default `2026`). `-p HOST:CONTAINER` only controls the host side, so you can expose the proxy under any port without touching its configuration:

```sh
podman run -d --name container-socket-proxy --restart unless-stopped \
  -p 127.0.0.1:9000:2026 \
  -v /run/podman/podman.sock:/run/podman/podman.sock \
  -e ALLOW_CONTAINERS=1 \
  container-socket-proxy

curl http://127.0.0.1:9000/_ping
```

Clients talk to the host port (`9000` here). Containers on a shared Podman network reach the proxy directly at `2026` regardless of the mapping. To change the port the proxy itself listens on, set `PROXY_PORT`—the image's `HEALTHCHECK` follows it automatically.

### Toggle recipes

- **Read-only dashboard** (status, stats): `ALLOW_CONTAINERS=1 ALLOW_IMAGES=1 ALLOW_INFO=1 ALLOW_VERSION=1` and nothing else. Used by the [Homepage example](homepage.md).
- **Read-only inventory for scripts**: add `ALLOW_VERSION=1` if your client checks the API version at handshake, `ALLOW_PODS=1` if it speaks the native Podman API.
- **Log forwarding**: add `ALLOW_EVENTS=1`.
- **CI that builds and runs containers**: `ALLOW_CONTAINERS=1 ALLOW_IMAGES=1 ALLOW_BUILD=1 ALLOW_WRITE=1`—a deliberate, auditable grant of write power.
- **Never enable a group "just in case".** The proxy's value is the shortest possible list.

## Connecting clients

Any client that speaks the Docker/Podman HTTP API works:

```sh
# Podman remote client
podman --remote --url http://127.0.0.1:2026 ps
podman --remote --url http://127.0.0.1:2026 info

# Docker CLI
DOCKER_HOST=http://127.0.0.1:2026 docker ps

# Raw curl (Podman-native endpoints are available too)
curl http://127.0.0.1:2026/_ping
curl http://127.0.0.1:2026/libpod/pods/json
```

The last command needs `ALLOW_PODS=1`. Without it the proxy answers `403`.

`podman --remote` and the Docker CLI use the Docker-compatible endpoints; native `/libpod/*` paths are only used by Podman-native clients.

A denied request tells you exactly why:

```console
$ curl -i http://127.0.0.1:2026/volumes/json
HTTP/1.1 403 Forbidden
...
container-socket-proxy: ALLOW_VOLUMES is not enabled
```

## Security guidance

- **Bind to loopback or a private network.** Use `-p 127.0.0.1:2026:2026`, or publish nothing and let other containers reach the proxy over a shared Podman network (see the [Homepage example](homepage.md)).
- **Prefer read-only.** Leave `ALLOW_WRITE` off unless a client genuinely mutates state.
- **Run one proxy per trust level.** A read-only proxy for dashboards and a separate write-enabled proxy for a privileged tool beats one broad proxy for everything.
- **Mind the threat model.** The proxy gates the API surface exposed through it. Whoever controls the proxy container's environment (or can start a sibling container with different toggles) can enable anything, so treat it as an access-control convenience layer, not a security boundary against its own operator.
- **Never publish the proxy to untrusted networks without TLS or an authenticating reverse proxy in front.** The proxy itself does no authentication.

## Troubleshooting

On startup the proxy logs what it does:

```console
2026-09-07 18:23:02,892 INFO container_socket_proxy listening on 0.0.0.0:2026 forwarding to /run/podman/podman.sock
2026-09-07 18:23:02,892 INFO container_socket_proxy enabled endpoint groups: ALLOW_CONTAINERS, ALLOW_IMAGES, ALLOW_INFO, ALLOW_PING, ALLOW_VERSION
2026-09-07 18:23:23,295 INFO container_socket_proxy proxy allowed GET /_ping from 127.0.0.1 via ALLOW_PING -> 200 in 1.4 ms
2026-09-07 18:23:27,819 WARNING container_socket_proxy proxy denied POST /containers/create from 172.20.0.7: method POST requires ALLOW_WRITE
```

`podman logs <container>` is the first stop: the enabled-group list shows what your toggles actually resolved to, and every request line carries the client address, duration, and outcome—denied and rejected requests say why.

| Symptom | Cause and fix |
|---|---|
| `403 ... is not enabled` | The endpoint group's `ALLOW_*` variable is off. Enable it or use an allowed path. |
| `403 no enabled endpoint group matches this path` | The path belongs to no group (e.g. `/pods/json` instead of `/libpod/pods/json`). |
| `403 method POST requires ALLOW_WRITE` | Write methods need `ALLOW_WRITE=1` on top of the enabled group. |
| `501 hijacked connections are not supported` | Docker-compat raw-TCP upgrades (`exec.../start`, `attach`, `attach/ws`). Keep `ALLOW_EXEC=0` for compat clients; Podman-native exec streams through fine. |
| `502 container socket unreachable` | `CONTAINER_SOCKET` points at the wrong path, the socket unit is not running (`systemctl status podman.socket`), or the container user cannot read the socket (rootless: pass `--user "$(id -u):$(id -g)"`). |
| `413 request body exceeds MAX_BODY_BYTES` | Raise `MAX_BODY_BYTES` or drop `0` (unlimited). |
| Container exits with code `2` | Invalid configuration; the stderr message names the variable. |
| macOS: socket path not found | `podman build` / `run` execute inside the podman-machine VM, so `-v /run/podman/podman.sock:...` resolves inside the VM. To run the proxy directly on the macOS host, point `CONTAINER_SOCKET` at `$XDG_RUNTIME_DIR/podman/podman.sock`. |
| Fedora/RHEL (SELinux): permission denied on the socket | Rootful containers may be denied access to the bind-mounted socket label. Run the proxy with `--security-opt label=disable` (Quadlet: `SecurityLabelDisable=true`). Do **not** use `:Z` on the socket—it relabels the host socket and breaks Podman itself. |
| If a client fails at handshake, enable `ALLOW_VERSION=1` and `ALLOW_INFO=1` (read-only) and retry | Some SDKs probe `/version` or `/info` before their first real call. |
