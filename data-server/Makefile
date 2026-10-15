# Symposium Data server: the image, and the Helm chart that deploys it on Kubernetes.
#   make test                      lint, the image build, the pinned Kubernetes tools and the
#                                  chart package, then side by side (make/side-by-side.mk): the
#                                  unit and integration suites (service-suites; the chart's lint
#                                  and render checks among them) and the chart's live test on a
#                                  throwaway kind cluster (chart-e2e). MAX_PER_TEST_WAIT
#                                  (seconds, default 120) is the one limit on any wait in them
#   make build-docker TAG=1.2.3    the image, tagged; image targets run no tests
#   make push-docker TAG=1.2.3     multi-arch push of :TAG and :latest (the release workflow, on a
#                                  data-server-v<version> GitHub release)
#   make helm-package              lint the chart, then dist/symposium-helm-<version>.tgz
#   make helm-push CHART_TAG=1.2.3 push it as oci://registry-1.docker.io/ndexbio/symposium-helm, once
#                                  its image is on Docker Hub (the release workflow, on a
#                                  symposium-helm-v<version> GitHub release)
#   make helm-attach CHART_TAG=…   attach that package to the symposium-helm-v<version> release
#   make chart-e2e                 the chart's live test on its own: the image, the Kubernetes
#                                  tools and the chart package first, then the test
# The chart targets fetch pinned helm, kind and kubectl into .tools/ on first use: Docker is the
# only tool they need on the machine.

IMAGE ?= ndexbio/symposium-data
TAG ?= $(shell sed -n 's/^version = "\(.*\)"/\1/p' service/pyproject.toml)
PLATFORMS ?= linux/amd64,linux/arm64
UV := uv run --frozen
# The one limit, in seconds, on any wait in the test suites (SYMPOSIUM_TEST_MAX_WAIT to them)
MAX_PER_TEST_WAIT ?= 120
export SYMPOSIUM_TEST_MAX_WAIT := $(MAX_PER_TEST_WAIT)

include ../make/side-by-side.mk

.PHONY: lint test service-suites chart-e2e build-docker push-docker helm-package helm-push \
	helm-attach k8s-tools chart-tag

# set while `test` runs: it has made the image, the tools and the package once, so the suites
# it runs side by side take them as made
export PREBUILT
test: PREBUILT := 1

lint:
	cd service && $(UV) ruff check . && $(UV) ruff format --check .

test: lint build-docker k8s-tools helm-package
	$(call side_by_side,service-suites chart-e2e)

# The suites themselves, on what `test` (or the repository's `make test`) made first: the unit
# suites, then the integration suites against the image
service-suites:
	cd service && $(UV) pytest tests/unit
	cd service && SYMPOSIUM_DATA_TEST_IMAGE=$(IMAGE):$(TAG) SYMPOSIUM_DATA_TEST_VERSION=$(TAG) \
		$(UV) pytest tests/integration

# the chart's live test: on its own it makes the image, the tools and the package first; under
# `test` (PREBUILT), on the ones already made
chart-e2e: $(if $(PREBUILT),,build-docker k8s-tools helm-package)
	$(E2E)

# the API's shared rules and contract, from outside this directory, as named build contexts
CONTEXTS := --build-context rules=../tools --build-context api=../api

build-docker:
	docker build -f docker/Dockerfile $(CONTEXTS) --build-arg DATA_VERSION=$(TAG) -t $(IMAGE):$(TAG) .

push-docker:
	docker buildx build --platform $(PLATFORMS) -f docker/Dockerfile $(CONTEXTS) \
		--build-arg DATA_VERSION=$(TAG) -t $(IMAGE):$(TAG) -t $(IMAGE):latest --push .

# ── pinned Kubernetes tools, fetched once per platform and checked against their checksums ──
HELM_VERSION := 4.3.0
KIND_VERSION := 0.33.0
KUBECTL_VERSION := 1.37.0
OS := $(shell uname -s | tr '[:upper:]' '[:lower:]')
ARCH := $(shell uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
PLATFORM := $(OS)-$(ARCH)
TOOLS := .tools/$(PLATFORM)
HELM := $(TOOLS)/helm-$(HELM_VERSION)
KIND := $(TOOLS)/kind-$(KIND_VERSION)
KUBECTL := $(TOOLS)/kubectl-$(KUBECTL_VERSION)
SHA256 := $(if $(filter darwin,$(OS)),shasum -a 256,sha256sum)
HELM_URL := https://get.helm.sh/helm-v$(HELM_VERSION)-$(PLATFORM).tar.gz
KIND_URL := https://github.com/kubernetes-sigs/kind/releases/download/v$(KIND_VERSION)/kind-$(PLATFORM)
KUBECTL_URL := https://dl.k8s.io/release/v$(KUBECTL_VERSION)/bin/$(OS)/$(ARCH)/kubectl

k8s-tools: $(HELM) $(KIND) $(KUBECTL)

# fetch(url, checksum url, target): download beside the target, then check it against the
# sha256 the tool's project publishes beside the download (its first word), so a broken or
# truncated download never runs
define fetch
	@mkdir -p $(TOOLS)
	curl -fsSL -o $(3).download $(1)
	@echo "$$(curl -fsSL $(2) | cut -d' ' -f1)  $(3).download" | $(SHA256) -c - > /dev/null \
		|| { rm -f $(3).download; echo "$(1): sha256 mismatch"; exit 1; }
endef

$(HELM):
	$(call fetch,$(HELM_URL),$(HELM_URL).sha256sum,$@)
	tar -xzf $@.download -O $(PLATFORM)/helm > $@ && chmod +x $@ && rm $@.download

$(KIND):
	$(call fetch,$(KIND_URL),$(KIND_URL).sha256sum,$@)
	mv $@.download $@ && chmod +x $@

$(KUBECTL):
	$(call fetch,$(KUBECTL_URL),$(KUBECTL_URL).sha256,$@)
	mv $@.download $@ && chmod +x $@

# ── the Helm chart ──────────────────────────────────────────────────────────────────────────
CHART := helm/symposium-helm
CHART_VERSION := $(shell sed -n 's/^version: *//p' $(CHART)/Chart.yaml)
APP_VERSION := $(shell sed -n 's/^appVersion: *"\(.*\)"/\1/p' $(CHART)/Chart.yaml)
PACKAGE := dist/symposium-helm-$(CHART_VERSION).tgz
REGISTRY := registry-1.docker.io
# helm push names the namespace only: the chart's name and version make ndexbio/symposium-helm:<v>
CHART_REPO := oci://$(REGISTRY)/$(firstword $(subst /, ,$(IMAGE)))

helm-package: $(HELM)
	$(HELM) lint --strict $(CHART)
	$(HELM) package $(CHART) -d dist

# a release's version must be the chart's own: a tag never publishes a chart under another number
chart-tag:
	@test -n "$(CHART_TAG)" || { echo "CHART_TAG is not set: the release's version, e.g. $(CHART_VERSION)"; exit 1; }
	@test "$(CHART_TAG)" = "$(CHART_VERSION)" || \
		{ echo "CHART_TAG $(CHART_TAG) is not the chart's version $(CHART_VERSION) ($(CHART)/Chart.yaml)"; exit 1; }

# a chart is never published before the image it deploys
helm-push: chart-tag helm-package
	@docker manifest inspect $(IMAGE):$(APP_VERSION) > /dev/null || \
		{ echo "$(IMAGE):$(APP_VERSION), the chart's appVersion, is not on Docker Hub: release data-server-v$(APP_VERSION) first"; exit 1; }
	@test -n "$$DOCKERHUB_USERNAME" -a -n "$$DOCKERHUB_TOKEN" || \
		{ echo "DOCKERHUB_USERNAME and DOCKERHUB_TOKEN must be set"; exit 1; }
	@echo "$$DOCKERHUB_TOKEN" | $(HELM) registry login $(REGISTRY) -u "$$DOCKERHUB_USERNAME" --password-stdin
	$(HELM) push $(PACKAGE) $(CHART_REPO)

helm-attach: chart-tag helm-package
	gh release upload "symposium-helm-v$(CHART_VERSION)" $(PACKAGE) --clobber

# the image this commit builds, on a kind cluster that exists only for the test; with no pytest
# cache, which the integration suites running beside it keep in the same directory
E2E = cd service && SYMPOSIUM_DATA_TEST_IMAGE=$(IMAGE):$(TAG) SYMPOSIUM_K8S_CHART=$(CURDIR)/$(PACKAGE) \
	SYMPOSIUM_K8S_HELM=$(CURDIR)/$(HELM) SYMPOSIUM_K8S_KIND=$(CURDIR)/$(KIND) \
	SYMPOSIUM_K8S_KUBECTL=$(CURDIR)/$(KUBECTL) $(UV) pytest -p no:cacheprovider tests/k8s
