# Symposium. The only targets are lint, test and (with the skills) build.
#   make lint    ruff over all Python, then the toolchain's conformance suite
#   make test    lint, then the data server's suites (its one image build), then the top-level
#                suites against that same image. It is the single gate.
# The data server has its own Makefile: make -C data-server test runs its suites alone.

UV := uv run --project data-server/service --frozen
# The image `make -C data-server test` builds: the top-level suites run against the same one.
IMAGE := ndexbio/symposium-data
TAG := $(shell sed -n 's/^version = "\(.*\)"/\1/p' data-server/service/pyproject.toml)
# The top-level suite (tests/): the CLI's tests, then the skill's, on one container.
SUITES := tests/symposium-data tests/skills

.PHONY: lint test

lint:
	$(UV) ruff check .
	$(UV) ruff format --check data-server tools/symposium-data tests skills
	cd tools && python3 conformance.py

test: lint
	$(MAKE) -C data-server test
	SYMPOSIUM_DATA_TEST_IMAGE=$(IMAGE):$(TAG) SYMPOSIUM_DATA_TEST_VERSION=$(TAG) \
		$(UV) pytest -c tests/pytest.ini $(SUITES)
