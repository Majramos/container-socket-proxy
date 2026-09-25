# Running containers with Podman Quadlets

Quadlet is Podman's systemd generator: you describe containers, networks, and volumes in small unit files and systemd manages their lifecycle, start order, restarts, boot persistence, and `journalctl` logging. No `docker-compose`, no hand-written unit files.

This page explains how quadlet units work in general, then walks through a concrete example: the [Homepage example](homepage.md) stack with a read-only socket proxy and the Homepage dashboard on a private network.

## Where quadlet files live

| Mode | Search path |
| --- | --- |
| Rootful (system units) | `/etc/containers/systemd/` |
| Rootless (user units) | `~/.config/containers/systemd/` |

A `name.container` file generates a `name.service` systemd unit and a Podman container named `systemd-name` (overridable with `ContainerName=`). Quadlet applies the `[Install]` section at generation time, so units with `WantedBy=` start on boot without `systemctl enable` (which does not work on generated units).

## Example: the Homepage stack

Three files, deployed as root to `/etc/containers/systemd/`:

| File | Creates |
| --- | --- |
| `homepage-net.network` | the shared `systemd-homepage-net` network |
| `container-socket-proxy-homepage.container` | read-only proxy for Homepage |
| `homepage.container` | the Homepage dashboard |

The proxy image must exist on the host: run `podman build -t container-socket-proxy:latest .` first. (Alternative: place a `container-socket-proxy.build` quadlet inside the repository checkout `ImageTag=container-socket-proxy:latest`, `File=Containerfile`, `SetWorkingDirectory=unit` and point the proxy unit's `Image=` at `container-socket-proxy.build`. Quadlet then builds the image on demand as a dependency.)

### homepage-net.network

```ini
[Unit]
Description=Private network for the dashboard stack

[Network]
```

Referencing `homepage-net.network` from the containers below makes quadlet create the network (named `systemd-homepage-net`) and add the dependency automatically.

### container-socket-proxy-homepage.container

Note there is no `--restart=always` equivalent here: systemd owns restarts via `Restart=always`. The toggles are the same as the `podman run` version, so any recipe from [guide.md](guide.md#toggle-recipes) translates one `Environment=` line per variable.

The proxy needs no `HealthCmd=`: the image ships a `HEALTHCHECK` (busybox `wget` against `/_ping` on `PROXY_PORT`, default `2026`) that quadlet-managed containers inherit automatically. This works because `ALLOW_PING` is the only default-on toggle. Setting `ALLOW_PING=0` denies `/_ping` and makes the healthcheck fail, so leave it on even if nothing else uses it.

`PublishPort=` mirrors `-p`: the host side (`127.0.0.1:8081`) is a free choice used only for the debugging curls, while the container side is `PROXY_PORT` (`2026`), the port the proxy answers on inside `homepage-net`.

```ini
[Unit]
Description=Read-only Podman socket proxy for Homepage
Wants=homepage-net.network
After=homepage-net.network

[Container]
ContainerName=container-socket-proxy-homepage
Image=container-socket-proxy:latest
Network=homepage-net.network
PublishPort=127.0.0.1:8081:2026
Volume=/run/podman/podman.sock:/run/podman/podman.sock
Environment=ALLOW_CONTAINERS=1
Environment=ALLOW_IMAGES=1
Environment=ALLOW_INFO=1
Environment=ALLOW_VERSION=1

[Service]
Restart=always

[Install]
WantedBy=multi-user.target
```

### homepage.container

`ContainerName=homepage` keeps the DNS name identical to the `podman run` example, so `docker.yaml` (`host: container-socket-proxy-homepage`) and `services.yaml` need no changes. Put the config files from [homepage.md](homepage.md#3-homepage) in `/srv/homepage`:

```ini
[Unit]
Description=Homepage dashboard
Wants=container-socket-proxy-homepage.container
After=container-socket-proxy-homepage.container

[Container]
ContainerName=homepage
Image=ghcr.io/gethomepage/homepage:latest
Network=homepage-net.network
PublishPort=3000:3000
Volume=/srv/homepage:/app/config

[Service]
Restart=always

[Install]
WantedBy=multi-user.target
```

Quadlet translates `Wants=`/`After=` references to other quadlet files into dependencies between the generated services, so Homepage starts after its proxy.

## Install and manage

```sh
sudo cp homepage-net.network \
        container-socket-proxy-homepage.container \
        homepage.container \
        /etc/containers/systemd/

sudo systemctl daemon-reload
sudo systemctl start \
  container-socket-proxy-homepage.service \
  homepage.service
```

Day-to-day:

```sh
systemctl status container-socket-proxy-homepage.service
systemctl restart homepage.service
journalctl -u container-socket-proxy-homepage.service -f
```

To change toggles, edit the `.container` file, `daemon-reload` again, and restart the unit. Quadlet regenerates the service, and Podman replaces the container.

## Rootless variant

Rootless quadlets run under the user manager. First make sure the rootless Podman socket exists across boots:

```sh
systemctl --user enable --now podman.socket
sudo loginctl enable-linger "$USER"
```

Then place the same three files in `~/.config/containers/systemd/` with these differences:

| Key | Rootful value | Rootless value |
| --- | --- | --- |
| `Volume=` (proxy) | `/run/podman/podman.sock:/run/podman/podman.sock` | `%t/podman/podman.sock:/run/podman/podman.sock` |
| `User=` / `Group=` (proxy) | not needed | `User=%U` and `Group=%U` |
| `Volume=` (homepage) | `/srv/homepage:/app/config` | `%h/homepage/config:/app/config` |
| `[Install]` | `WantedBy=multi-user.target` | `WantedBy=default.target` |

`%t` is systemd's runtime directory (`/run/user/$UID`), so the socket path never needs hardcoding; `User=`/`Group=` mirror the `--user "$(id -u):$(id -g)"` guidance for rootless sockets. `%U` expands to your UID. If your UID and GID differ, use numeric values instead (for example `User=1000` and `Group=1000`). Manage everything with `systemctl --user daemon-reload` and `systemctl --user start ...`; logs land in `journalctl --user -u <unit>`.

Rootless Podman requires cgroup v2.

## SELinux note (Fedora/RHEL)

If the proxy unit starts but answers `502 container socket unreachable` with the socket bind-mounted, SELinux is likely denying the container access to the socket's label. Add to the proxy file:

```ini
SecurityLabelDisable=true
```

Never add `:Z` to the socket mount. Relabeling the host socket breaks Podman itself. Plain config directories (like `/srv/homepage:/app/config`) are the opposite case: there `:Z` is the right fix if SELinux denies the read.

## Debugging quadlet files

If `systemctl start` reports `Unit ... not found`, the generator rejected a file. See what it produces (and where it errors) without touching real units:

```sh
# Rootful
sudo /usr/lib/systemd/system-generators/podman-system-generator --dryrun

# Rootless
/usr/lib/systemd/system-generators/podman-system-generator --user --dryrun

# Lint a single generated unit
systemd-analyze verify container-socket-proxy-homepage.service
```

The generator path varies by distribution (for example `/usr/libexec/systemd/system-generators/podman-system-generator`). The dry run prints each generated `ExecStart=podman run ...` line. Check that specifier expansion (`%t`, `%h`, `%U`) produced the paths you expect.
