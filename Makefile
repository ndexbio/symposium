# Symposium. The only targets are lint, test and (with the skills) build.
#   make lint    ruff over all Python, then the toolchain's conformance suite
#   make test    lint, then the data server's suites (its one image build), then the top-level
#                suites against that same image. It is the single gate.
# The data server has its own Makefile: make -C data-server test runs its suites alone.

UV := uv run --project data-server/service --frozen
# The image `make -C data-server test` builds: the top-level suites run against the same one.
IMAGE := ndexbio/symposium-data
TAG := $(shell sed -n 's/^version = "\(.*\)"/\1/p' data-server/service/pyproject.toml)
# The CLI and skill suites import the shared harness and fixtures from the data server's tests.
SUITES := tools/symposium-data/tests

.PHONY: lint test

lint:
	$(UV) ruff check .
	$(UV) ruff format --check data-server tools/symposium-data
	cd tools && python3 conformance.py

test: lint
	$(MAKE) -C data-server test
	SYMPOSIUM_DATA_TEST_IMAGE=$(IMAGE):$(TAG) SYMPOSIUM_DATA_TEST_VERSION=$(TAG) \
		PYTHONPATH=data-server/service/tests $(UV) pytest $(SUITES)
