.PHONY: test lint fmt fmt-check build

test:
	pytest --cov=src -q

lint:
	ruff check .

fmt:
	black .

fmt-check:
	black --check .

build:
	python -m build
