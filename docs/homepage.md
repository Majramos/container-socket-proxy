# Example: Homepage behind container-socket-proxy

This example deploys a self-hosted dashboard stack where [Homepage](https://gethomepage.dev) gets exactly the access it needs — and nothing more: a **read-only** proxy that can list containers and read stats, but can never start, stop, or create anything.

```
Homepage ──> container-socket-proxy-homepage (read-only) ──> /run/podman/podman.sock ──> Podman API
```

If you later add a client that needs write access (a CI runner, a management UI), don't widen this proxy — run a second one with its own toggles and keep one proxy per trust level. The same stack as systemd quadlets is in [quadlets.md](quadlets.md).

Prerequisites (from the repository root):

```sh
sudo systemctl enable --now podman.socket
podman build -t container-socket-proxy .
```

Homepage speaks the Docker-compatible API against the rootful socket in this example. The rootless socket works too — see [podman-run.md](podman-run.md#example-2-rootless-proxy) for the proxy changes it needs.

## 1. Shared network

The two containers talk over one private Podman network; the proxy is not published to the LAN at all (loopback only, for debugging).

```sh
podman network create homepage-net
```

## 2. The read-only proxy

```sh
podman run -d --name container-socket-proxy-homepage --restart unless-stopped \
  --network homepage-net \
  -p 127.0.0.1:8081:2026 \
  -v /run/podman/podman.sock:/run/podman/podman.sock \
  -e ALLOW_CONTAINERS=1 \
  -e ALLOW_IMAGES=1 \
  -e ALLOW_INFO=1 \
  -e ALLOW_VERSION=1 \
  container-socket-proxy
```

`ALLOW_CONTAINERS` is what Homepage actually uses (`GET /containers/json` and `GET /containers/{id}/stats`). `ALLOW_VERSION` / `ALLOW_INFO` satisfy clients that probe the API at handshake. No `ALLOW_WRITE` — a `POST` to this proxy answers `403`.

The remapped loopback port `-p 127.0.0.1:8081:2026` publishes the proxy under an arbitrary host port for debugging. Inside `homepage-net` it is always reached at its real port, `2026` — which is why `docker.yaml` says `port: 2026`.

## 3. Homepage

Homepage reads its configuration from files under `/app/config`. Create the directory and config files on the host, then run the container:

```sh
mkdir -p ~/homepage/config
```

`~/homepage/config/docker.yaml` — tells Homepage where the Docker-compatible API lives. The hostname is the read-only proxy's container name, resolved over `homepage-net`:

```yaml
my-podman:
  host: container-socket-proxy-homepage
  port: 2026
```

`~/homepage/config/services.yaml` — a service entry tied to a container on that instance. `server` is the key defined in `docker.yaml`, `container` is the container name to watch. `showStats` adds CPU/memory numbers to the status tooltip:

```yaml
- Infra:
    - Homepage:
        icon: homepage.png
        href: http://localhost:3000
        description: This dashboard
        server: my-podman
        container: homepage
        showStats: true
```

(Optionally set a title and theme in `settings.yaml`, e.g. `title: My Homelab` — see the [Homepage docs](https://gethomepage.dev/configs/settings/).)

Run it:

```sh
podman run -d --name homepage --restart unless-stopped \
  --network homepage-net \
  -p 3000:3000 \
  -v ~/homepage/config:/app/config \
  ghcr.io/gethomepage/homepage:latest
```

Open `http://localhost:3000`: the services show a green/red status dot, and clicking it reveals live stats fetched through the read-only proxy.

Instead of hand-writing every service, you can let Homepage discover containers automatically by attaching `homepage.*` labels to them, e.g. `--label homepage.group=Infra --label homepage.name=Homepage` on any container (see [Docker service discovery](https://gethomepage.dev/configs/docker/#automatic-service-discovery)).

## 4. Verify

```sh
# Proxy alive
curl http://127.0.0.1:8081/_ping

# Container list works
curl http://127.0.0.1:8081/containers/json

# ...but writes are denied (403)
curl -X POST http://127.0.0.1:8081/containers/create

# Watch what the proxy lets through
podman logs -f container-socket-proxy-homepage
```

On the dashboard, Homepage's services should show status and stats.

## Limitations

- **Pods are invisible.** Homepage speaks the Docker-compatible API, which has no pods; `ALLOW_PODS` only matters for Podman-native clients.
- **Hijacked connections are rejected.** Docker-compat raw-TCP upgrades (`exec`, `.../start`, `attach`, `attach/ws`) answer `501` by design — logs and stats work fine because they are plain streaming HTTP.
- **Rootless Podman** works through the same proxy but expect rough edges; the proxy needs `--user` matching the socket owner. See [podman-run.md](podman-run.md#example-2-rootless-proxy) for the setup.
- **SELinux** (Fedora/RHEL): if the proxy container can't open the bind-mounted socket, add `--security-opt label=disable` to its `podman run` command. Never use `:Z` on the socket — it relabels the host socket and breaks Podman itself.
