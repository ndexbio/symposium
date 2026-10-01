# Symposium. The only targets are lint, test and (with the skills) build.
#   make lint    ruff over all Python, then the toolchain's conformance suite
#   make test    lint, then the top-level test suites
# The data server has its own Makefile: make -C data-server test

UV := uv run --project data-server/service --frozen

.PHONY: lint test

lint:
	$(UV) ruff check .
	$(UV) ruff format --check data-server
	cd tools && python3 conformance.py

test: lint
	@echo "top-level test suites: none yet"
