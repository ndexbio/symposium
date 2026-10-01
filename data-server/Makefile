# Symposium Data server. The only targets are lint, test, build-docker and push-docker.
#   make test                      lint, unit suites, image build, integration suites
#   make build-docker TAG=1.2.3    the tested image, tagged
#   make push-docker TAG=1.2.3     multi-arch push of :TAG and :latest (release workflow)

IMAGE ?= ndexbio/symposium-data
TAG ?= $(shell sed -n 's/^version = "\(.*\)"/\1/p' service/pyproject.toml)
PLATFORMS ?= linux/amd64,linux/arm64
UV := uv run --frozen

.PHONY: lint test build-docker push-docker

lint:
	cd service && $(UV) ruff check . && $(UV) ruff format --check .

test: lint
	cd service && $(UV) pytest tests/unit
	docker build -f docker/Dockerfile --build-arg DATA_VERSION=$(TAG) -t $(IMAGE):$(TAG) .
	cd service && SYMPOSIUM_DATA_TEST_IMAGE=$(IMAGE):$(TAG) SYMPOSIUM_DATA_TEST_VERSION=$(TAG) \
		$(UV) pytest tests/integration

build-docker: test
	docker image inspect $(IMAGE):$(TAG) > /dev/null

push-docker: build-docker
	docker buildx build --platform $(PLATFORMS) -f docker/Dockerfile \
		--build-arg DATA_VERSION=$(TAG) -t $(IMAGE):$(TAG) -t $(IMAGE):latest --push .
