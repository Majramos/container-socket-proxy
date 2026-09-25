import logging
import signal
import sys
import threading
from types import FrameType

from container_socket_proxy.config import load_config
from container_socket_proxy.proxy import ProxyServer

logger = logging.getLogger("container_socket_proxy")


def main() -> None:
    try:
        config = load_config()
    except ValueError as exc:
        print(f"invalid configuration: {exc}", file=sys.stderr)
        sys.exit(2)
    logging.basicConfig(
        level=int(getattr(logging, config.log_level)),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    server = ProxyServer((config.host, config.port), config)

    def request_shutdown(signum: int, frame: FrameType | None) -> None:
        threading.Thread(target=server.shutdown).start()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    enabled = [name for name, value in sorted(config.toggles.items()) if value]
    logger.info(
        "listening on %s:%s forwarding to %s", config.host, config.port, config.socket
    )
    logger.info(
        "enabled endpoint groups: %s", ", ".join(enabled) if enabled else "none"
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        logger.info("stopped")


if __name__ == "__main__":
    main()
