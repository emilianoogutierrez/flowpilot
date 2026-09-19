.PHONY: bootstrap dev build test typecheck check benchmark

bootstrap:
	python scripts/bootstrap.py

dev:
	python scripts/dev.py

build:
	npm run build

test:
	python -m pytest
	npm test

typecheck:
	npm run typecheck

check:
	python scripts/check.py

benchmark:
	python scripts/benchmark.py --runs 100
