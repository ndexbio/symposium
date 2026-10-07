# Symposium Data server. The only targets are lint, test, build-docker and push-docker.
#   make test                      lint, the image build, unit suites, integration suites
#   make build-docker TAG=1.2.3    the image, tagged; image targets run no tests
#   make push-docker TAG=1.2.3     multi-arch push of :TAG and :latest (release workflow, from a
#                                  data-store commit CI has tested)

IMAGE ?= ndexbio/symposium-data
TAG ?= $(shell sed -n 's/^version = "\(.*\)"/\1/p' service/pyproject.toml)
PLATFORMS ?= linux/amd64,linux/arm64
UV := uv run --frozen

.PHONY: lint test build-docker push-docker

lint:
	cd service && $(UV) ruff check . && $(UV) ruff format --check .

test: lint build-docker
	cd service && $(UV) pytest tests/unit
	cd service && SYMPOSIUM_DATA_TEST_IMAGE=$(IMAGE):$(TAG) SYMPOSIUM_DATA_TEST_VERSION=$(TAG) \
		$(UV) pytest tests/integration

# the API's shared rules and contract, from outside this directory, as named build contexts
CONTEXTS := --build-context rules=../tools --build-context api=../api

build-docker:
	docker build -f docker/Dockerfile $(CONTEXTS) --build-arg DATA_VERSION=$(TAG) -t $(IMAGE):$(TAG) .

push-docker:
	docker buildx build --platform $(PLATFORMS) -f docker/Dockerfile $(CONTEXTS) \
		--build-arg DATA_VERSION=$(TAG) -t $(IMAGE):$(TAG) -t $(IMAGE):latest --push .
