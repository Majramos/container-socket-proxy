FROM python:3.13-alpine

WORKDIR /app

COPY main.py ./
COPY container_socket_proxy/ ./container_socket_proxy/

ENV PROXY_HOST=0.0.0.0 \
    PROXY_PORT=2026 \
    CONTAINER_SOCKET=/run/podman/podman.sock \
    ALLOW_PING=1 \
    LOG_LEVEL=INFO

EXPOSE 2026

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null "http://127.0.0.1:${PROXY_PORT}/_ping" || exit 1

ENTRYPOINT [ "python", "main.py" ]
