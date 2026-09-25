# container-socket-proxy documentation

A dependency-free HTTP proxy that sits in front of a Podman or Docker socket and only forwards the endpoint groups you explicitly enable. Clients talk the Podman/Docker HTTP API to the proxy; anything not enabled answers `403`.

Typical use: give CI jobs, dashboards, or monitoring agents limited (often read-only) access to Podman or Docker without handing them full control of the host. Treat the proxy as an access-control convenience layer, not a security boundary against its own operator - whoever controls the proxy container's environment can enable anything.

## Quick start

```sh
podman build -t container-socket-proxy .
sudo systemctl enable --now podman.socket

podman run -d --name container-socket-proxy --restart unless-stopped \
    -p 127.0.0.1:2026:2026 \
    -v /run/podman/podman.sock:/run/podman/podman.sock \
    -e ALLOW_CONTAINERS=1 \
    container-socket-proxy

curl http://127.0.0.1:2026/_ping
```

## Documentation

| Page | Contents |
| --- | --- |
| [Usage guide](guide.md) | How the access model works, prerequisites, the full configuration reference, toggle recipes, connecting clients, security guidance, and troubleshooting |
| [podman run examples](podman-run.md) | Read-only proxy (rootful and rootless), write-enabled CI proxy, proxying a remote Podman API |
| [Homepage example](homepage.md) | Read-only proxy for the Homepage dashboard on a private network |
| [quadlets](quadlets.md) | A generic guide to systemd-managed quadlet units (`.container`/`.network`), rootful and rootless, with the Homepage stack as the worked example, SELinux notes, and debugging commands |
