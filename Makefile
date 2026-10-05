# Symposium. The only targets are lint, test, build and deploy-local.
#   make lint           ruff over all Python, then the toolchain's conformance suite
#   make test           lint, then the data server's suites (its one image build), then the
#                       top-level suite against that same image. It is the single gate.
#   make build          lint, then dist/Symposium_skill.zip: the symposium skill, with the
#                       symposium-data CLI inside it (R-I8)
#   make deploy-local   build, then install the skill from the zip into $(SKILLS)
# The data server has its own Makefile: make -C data-server test runs its suites alone.

UV := uv run --project data-server/service --frozen
# The image `make -C data-server test` builds: the top-level suites run against the same one.
IMAGE := ndexbio/symposium-data
TAG := $(shell sed -n 's/^version = "\(.*\)"/\1/p' data-server/service/pyproject.toml)
# The top-level suite (tests/): the CLI's tests, then the skill's, on one container.
SUITES := tests/symposium-data tests/skills
BUNDLE := dist/Symposium_skill.zip
SKILLS ?= $(HOME)/.claude/skills

.PHONY: lint test build deploy-local

lint:
	$(UV) ruff check .
	$(UV) ruff format --check data-server tools/symposium-data tests skills
	cd tools && python3 conformance.py

test: lint
	$(MAKE) -C data-server test
	SYMPOSIUM_DATA_TEST_IMAGE=$(IMAGE):$(TAG) SYMPOSIUM_DATA_TEST_VERSION=$(TAG) \
		$(UV) pytest -c tests/pytest.ini $(SUITES)

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
	@echo "  usage: /symposium <setup|bootstrap|publish|sync|gate|validate|serve|port|admin-config|…> [options]    e.g. /symposium setup --invite-file <file>"
	@echo "  full instructions: $(SKILLS)/symposium/README.md"
