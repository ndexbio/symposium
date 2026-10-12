# Symposium. The only targets are lint, test, build and deploy-local.
#   make lint           the API's generated code against api/openapi.yaml, ruff over all
#                       Python, then the toolchain's conformance suite
#   make test           lint, then the API contract's OpenAPI lint (node and npx), then the
#                       data server's image build, pinned Kubernetes tools and chart package,
#                       then every suite side by side (make/side-by-side.mk): the data
#                       server's unit and integration suites, its Helm chart's live test on a
#                       throwaway kind cluster, and the top-level suite against that same image.
#                       It is the single gate.
#                       DOCKER=false runs only the suites that need no container
#                       (tests/skills/test_agent_process.py, test_sessions.py, test_runtime.py,
#                       and tests/api)
#                       MAX_PER_TEST_WAIT (seconds, default 120) is the one limit on any wait
#                       in any suite: reaching it means something hung
#   make build          lint, then dist/Symposium_skill.zip: the symposium skill, with the
#                       symposium-data CLI inside it (R-I8)
#   make deploy-local   build, then install the skill from the zip into $(SKILLS)
# The data server has its own Makefile: make -C data-server test runs its suites alone.

UV := uv run --project data-server/service --frozen
# The image the data server's Makefile builds (its test, or build-docker): the top-level suites
# run against the same one.
IMAGE := ndexbio/symposium-data
TAG := $(shell sed -n 's/^version = "\(.*\)"/\1/p' data-server/service/pyproject.toml)
# The top-level suite (tests/): the CLI's tests, then the skill's, on one container, then the
# API contract's, which need none.
SUITES := tests/symposium-data tests/skills tests/api
# DOCKER=false (CI's Windows job): only the suites that need no container
DOCKER ?= true
# The one limit, in seconds, on any wait in any test suite (SYMPOSIUM_TEST_MAX_WAIT to them)
MAX_PER_TEST_WAIT ?= 120
NO_DOCKER_SUITES := tests/skills/test_agent_process.py tests/skills/test_sessions.py \
	tests/skills/test_long_running.py tests/skills/test_watch_primitives.py \
	tests/skills/test_runtime.py tests/api
# The OpenAPI linter for the API contract (api/openapi.yaml), pinned; it runs through npx.
REDOCLY := 2.59.0
BUNDLE := dist/Symposium_skill.zip
SKILLS ?= $(HOME)/.claude/skills

include make/side-by-side.mk

.PHONY: lint api-lint test data-suites chart-e2e top-suite build deploy-local

lint:
	$(UV) python data-server/service/codegen/generate.py --check
	$(UV) ruff check .
	$(UV) ruff format --check data-server tools/symposium-data tests skills
	cd tools && python3 conformance.py

api-lint:
	npx --yes @redocly/cli@$(REDOCLY) lint --config api/redocly.yaml api/openapi.yaml

ifeq ($(DOCKER),false)
test:
	SYMPOSIUM_TEST_DOCKER=false SYMPOSIUM_TEST_MAX_WAIT=$(MAX_PER_TEST_WAIT) \
		$(UV) pytest -c tests/pytest.ini $(NO_DOCKER_SUITES)
else
# the lints first, so either fails before anything is built; then what every suite shares,
# made once; then the suites, side by side
test: lint api-lint
	$(MAKE) -C data-server lint build-docker k8s-tools helm-package
	$(call side_by_side,data-suites chart-e2e top-suite)
endif

data-suites:
	$(MAKE) -C data-server service-suites MAX_PER_TEST_WAIT=$(MAX_PER_TEST_WAIT)

chart-e2e:
	$(MAKE) -C data-server chart-e2e MAX_PER_TEST_WAIT=$(MAX_PER_TEST_WAIT)

top-suite:
	SYMPOSIUM_DATA_TEST_IMAGE=$(IMAGE):$(TAG) SYMPOSIUM_DATA_TEST_VERSION=$(TAG) \
		SYMPOSIUM_TEST_MAX_WAIT=$(MAX_PER_TEST_WAIT) $(UV) pytest -c tests/pytest.ini $(SUITES)

build: lint
	python3 tools/bundle.py $(BUNDLE)

# Installs from the built zip, not the working copy, so what runs locally is what ships. It
# removes before extracting, so a file dropped from the bundle does not live on in the install.
deploy-local: build
	@test -n "$(SKILLS)" || { echo "deploy-local: SKILLS is empty; refusing"; exit 1; }
	@staging=$$(mktemp -d) && trap 'rm -rf "$$staging"' EXIT && \
		python3 -m zipfile -e $(BUNDLE) "$$staging" && \
		rm -rf "$(SKILLS)/symposium" && \
		mkdir -p "$(SKILLS)" && \
		mv "$$staging/skills/symposium" "$(SKILLS)/symposium"
	@echo "/symposium skill installed in $(SKILLS)/symposium"
	@echo "  usage: /symposium <setup|bootstrap|use|publish|sync|gate|validate|serve|port|admin-config|…> [options]    e.g. /symposium setup --invite-file <file>"
	@echo "  full instructions: $(SKILLS)/symposium/README.md"
