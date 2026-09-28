PY := .venv/bin/python
DXT := .venv/bin/dxt

.PHONY: setup setup-gnn lint test sources verify check

setup:            ## venv + package + dev tools
	python3.12 -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -e ".[dev,baseline]"

setup-gnn: setup  ## + torch for Front A
	.venv/bin/pip install -q -e ".[gnn]"

lint:
	.venv/bin/ruff check src tests
	.venv/bin/ruff format --check src tests

test:
	.venv/bin/pytest

sources:          ## fetch and sha256-verify every pinned source into data/raw
	$(DXT) sources fetch

verify:           ## sources + frozen splits + manifests
	$(DXT) lineage verify

check: lint test verify
