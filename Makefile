.PHONY: install dev test lint fmt build docker run clean

install:
	uv pip install -e ".[dev]"

dev:
	uv run --with-editable . captcha-mcp

test:
	uv run pytest -q

lint:
	uv run ruff check src tests

fmt:
	uv run ruff format src tests

build:
	uv build

docker:
	docker build -t captcha-mcp:latest .

run:
	uv run captcha-mcp

clean:
	rm -rf dist build .pytest_cache .ruff_cache
