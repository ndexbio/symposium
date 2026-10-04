# Symposium. The only targets are lint, test and (with the skills) build.
#   make lint    ruff over all Python, then the toolchain's conformance suite
#   make test    lint, then the data server's suites (its one image build), then the top-level
#                suites against that same image. It is the single gate.
# The data server has its own Makefile: make -C data-server test runs its suites alone.

UV := uv run --project data-server/service --frozen

.PHONY: lint test

lint:
	$(UV) ruff check .
	$(UV) ruff format --check data-server
	cd tools && python3 conformance.py

test: lint
	$(MAKE) -C data-server test
	@echo "top-level test suites: none yet"
