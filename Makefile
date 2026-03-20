UV := UV_CACHE_DIR=.uv-cache uv
UV_SYNC_ARGS := --locked --group dev
FORMAT_TARGETS := src tests scripts
LINT_TARGETS := .
COMPILE_TARGETS := src tests scripts
TYPECHECK_PROJECT := basedpyrightconfig.json
TEST_TARGETS := tests
TEST_ARGS := -q

.PHONY: sync fmt fmt-check lint typecheck test ci

sync:
	$(UV) sync $(UV_SYNC_ARGS)

fmt:
	$(UV) run ruff format $(FORMAT_TARGETS)

fmt-check:
	$(UV) run ruff format --check $(FORMAT_TARGETS)

lint:
	$(UV) run ruff check $(LINT_TARGETS)

typecheck:
	$(UV) run basedpyright --project $(TYPECHECK_PROJECT)

test:
	$(UV) run pytest $(TEST_ARGS) $(TEST_TARGETS)

ci:
	$(UV) run python -m compileall -q $(COMPILE_TARGETS)
	$(MAKE) fmt-check
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) test
