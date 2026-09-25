# Running with podman run

Three copy-paste `podman run` recipes for the proxy itself: a read-only proxy for dashboards and monitoring, the rootless variant, and a write-enabled proxy for CI. For the full-stack Homepage example see [homepage.md](homepage.md); for systemd-managed deployments see [quadlets.md](quadlets.md).

Build the image first:

```sh
podman build -t container-socket-proxy .
```

## Example 1: read-only proxy (rootful)

Publishes on loopback only. The proxy can list containers and images and read system info, but cannot change anything: `ALLOW_WRITE` stays off, so every `POST`/`PUT`/`PATCH`/`DELETE` answers `403`.

```sh
sudo systemctl enable --now podman.socket

podman run -d --name container-socket-proxy --restart unless-stopped \
  -p 127.0.0.1:2026:2026 \
  -v /run/podman/podman.sock:/run/podman/podman.sock \
  -e ALLOW_CONTAINERS=1 \
  -e ALLOW_IMAGES=1 \
  -e ALLOW_INFO=1 \
  container-socket-proxy
```

Verify allowed, denied, and read-only:

```sh
# Proxy is alive
curl http://127.0.0.1:2026/_ping
# OK

# Enabled group: returns the container list
curl http://127.0.0.1:2026/containers/json

# Disabled group: 403 with the reason
curl http://127.0.0.1:2026/volumes/json
# container-socket-proxy: ALLOW_VOLUMES is not enabled

# Enabled group, but a write method: 403
curl -X POST http://127.0.0.1:2026/containers/create
# container-socket-proxy: method POST requires ALLOW_WRITE
```

And through real clients:

```sh
podman --remote --url http://127.0.0.1:2026 ps
DOCKER_HOST=http://127.0.0.1:2026 docker ps
```

The host side of `-p` is a free choice: `-p 127.0.0.1:9000:2026` exposes the same proxy at `http://127.0.0.1:9000` while the container keeps listening on `2026`.

## Example 2: rootless proxy

Same idea against the rootless socket. The image runs as root by default so it can reach root-owned sockets; for the rootless socket, pass `--user` matching the socket owner (see the [usage guide](guide.md) for prerequisites):

```sh
systemctl --user enable --now podman.socket

podman run -d --name container-socket-proxy --restart unless-stopped \
  -p 127.0.0.1:2026:2026 \
  --user "$(id -u):$(id -g)" \
  -v "/run/user/$(id -u)/podman/podman.sock:/run/podman/podman.sock" \
  -e ALLOW_CONTAINERS=1 \
  container-socket-proxy
```

## Example 3: write-enabled proxy for CI

A CI job that builds images and starts containers needs write access. This is a deliberate, auditable grant: with these toggles a client can create, start, and remove containers and images — treat the proxy's port as a secret. `MAX_BODY_BYTES` caps how large a single request body (e.g. a build context upload) may be.

```sh
podman run -d --name container-socket-proxy-ci --restart unless-stopped \
  -p 127.0.0.1:2026:2026 \
  -v /run/podman/podman.sock:/run/podman/podman.sock \
  -e ALLOW_CONTAINERS=1 \
  -e ALLOW_IMAGES=1 \
  -e ALLOW_BUILD=1 \
  -e ALLOW_WRITE=1 \
  -e MAX_BODY_BYTES=104857600 \
  container-socket-proxy
```

The proxy logs every allowed and denied request, so `podman logs container-socket-proxy-ci` doubles as an audit trail of what the CI did.

## Proxying a remote Podman API

`CONTAINER_SOCKET` also accepts URLs, so the proxy can gate a Podman API that already listens on TCP, without touching a local socket:

```sh
podman run -d --name container-socket-proxy --restart unless-stopped \
  -p 127.0.0.1:2026:2026 \
  -e CONTAINER_SOCKET=tcp://podman.internal:8080 \
  -e ALLOW_CONTAINERS=1 \
  container-socket-proxy
```

`unix://` and `http(s)://` URLs work the same way.

## Cleanup

```sh
podman rm -f container-socket-proxy container-socket-proxy-ci
```
