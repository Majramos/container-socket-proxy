.RECIPEPREFIX := $() $()
CONTAINER_CLI ?= $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)

.PHONY: install run image test style lint fmt format-check clean verify setup-pre-commit

install:
    uv sync

run:
    uv run main.py

image:
    @test -n "$(CONTAINER_CLI)" || { echo "error: neither podman nor docker found in PATH" >&2; exit 1; }
    $(CONTAINER_CLI) build -f Containerfile -t container-socket-proxy .

test:
    uv run pytest -v

style:
    uv run mypy main.py container_socket_proxy tests

lint:
    uv run ruff check .

fmt:
    uv run ruff format .

verify: lint style test

clean:
    find . -type d -name __pycache__ -exec rm -rf {} +
    find . -type f -name "*.pyc" -delete
    rm -rf .pytest_cache .ruff_cache .mypy_cache

setup-pre-commit:
    uv run pre-commit install
    uv run pre-commit install --hook-type commit-msg
