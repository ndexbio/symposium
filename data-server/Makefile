# Symposium Data server: the image, and the Helm chart that deploys it on Kubernetes.
#   make test                      lint, the image build, unit suites, integration suites (the
#                                  chart's lint and render checks among them); K8S=true adds the
#                                  chart's live test on a throwaway kind cluster (helm-e2e)
#   make build-docker TAG=1.2.3    the image, tagged; image targets run no tests
#   make push-docker TAG=1.2.3     multi-arch push of :TAG and :latest (the release workflow, on a
#                                  data-server-v<version> GitHub release)
#   make helm-package              lint the chart, then dist/symposium-helm-<version>.tgz
#   make helm-push CHART_TAG=1.2.3 push it as oci://registry-1.docker.io/ndexbio/symposium-helm, once
#                                  its image is on Docker Hub (the release workflow, on a
#                                  symposium-helm-v<version> GitHub release)
#   make helm-attach CHART_TAG=…   attach that package to the symposium-helm-v<version> release
#   make helm-e2e                  the chart's live test on its own
# The chart targets fetch pinned helm, kind and kubectl into .tools/ on first use: Docker is the
# only tool they need on the machine.

IMAGE ?= ndexbio/symposium-data
TAG ?= $(shell sed -n 's/^version = "\(.*\)"/\1/p' service/pyproject.toml)
PLATFORMS ?= linux/amd64,linux/arm64
UV := uv run --frozen
K8S ?= false

.PHONY: lint test build-docker push-docker helm-package helm-push helm-attach helm-e2e \
	k8s-tools chart-tag

lint:
	cd service && $(UV) ruff check . && $(UV) ruff format --check .

test: lint build-docker $(if $(filter true,$(K8S)),k8s-tools helm-package)
	cd service && $(UV) pytest tests/unit
	cd service && SYMPOSIUM_DATA_TEST_IMAGE=$(IMAGE):$(TAG) SYMPOSIUM_DATA_TEST_VERSION=$(TAG) \
		$(UV) pytest tests/integration
ifeq ($(K8S),true)
	$(E2E)
endif

# the API's shared rules and contract, from outside this directory, as named build contexts
CONTEXTS := --build-context rules=../tools --build-context api=../api

build-docker:
	docker build -f docker/Dockerfile $(CONTEXTS) --build-arg DATA_VERSION=$(TAG) -t $(IMAGE):$(TAG) .

push-docker:
	docker buildx build --platform $(PLATFORMS) -f docker/Dockerfile $(CONTEXTS) \
		--build-arg DATA_VERSION=$(TAG) -t $(IMAGE):$(TAG) -t $(IMAGE):latest --push .

# ── pinned Kubernetes tools, fetched once per platform and checked by sha256 ─────────────────
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

HELM_SHA_linux-amd64 := 86584a54def73570558f66f5111cc53dfed56689637ae32c1201205d494f54fb
HELM_SHA_linux-arm64 := 31c5794dd55c66a51e6b7d2e2ac7a114ae8b1de41ff1d9ba51748ac973b06a08
HELM_SHA_darwin-amd64 := 347a784877e0e20eac865e8d1c36a80f6bb0861d6f29abd34defb6570ef95d92
HELM_SHA_darwin-arm64 := d3870437e1e95b67f8edbde964156c84a26503f560821d40c542441658934fba
KIND_SHA_linux-amd64 := aee6151561422756b764a4ae28e7f44cda5af5a9eead3cc9985112b1de8d8e0d
KIND_SHA_linux-arm64 := 20022bee6cfcd5086cb7234d218e3454e6090022f2a8f55d1fa7fcf42c3867a2
KIND_SHA_darwin-amd64 := 5a99f26f57246dc9319dd294803313197a0f34d33c525b3ea8b655db5916ece0
KIND_SHA_darwin-arm64 := 0c8c7dbe5e23594a198b786c4bc13dacc101fa6196b0cb0b23a1ca44e61f4b4f
KUBECTL_SHA_linux-amd64 := 6129359f4e1f3848a5572ccb0b26cf28b8ca08cef38c95a765b2f64a2c961a2f
KUBECTL_SHA_linux-arm64 := 922df28df248cc00a9e025f947704f1d1482de64ece54cfe57e61f19eaf1eef3
KUBECTL_SHA_darwin-amd64 := d5276c0f4fde77fc446070290f345944a7f1fda153df6b960e5fde93b7a9bccd
KUBECTL_SHA_darwin-arm64 := 583beedaebe422e71d3f1a96acef8b1fef86ea2f09a45ad01aa6c9ce287c1380

k8s-tools: $(HELM) $(KIND) $(KUBECTL)

# fetch(url, sha256, target): download beside the target, check it, then move it into place
define fetch
	@test -n "$(2)" || { echo "no pinned $(notdir $(3)) for $(PLATFORM): linux and darwin, amd64 and arm64"; exit 1; }
	@mkdir -p $(TOOLS)
	curl -fsSL -o $(3).download $(1)
	@echo "$(2)  $(3).download" | $(SHA256) -c - > /dev/null || { rm -f $(3).download; echo "$(1): sha256 mismatch"; exit 1; }
endef

$(HELM):
	$(call fetch,https://get.helm.sh/helm-v$(HELM_VERSION)-$(PLATFORM).tar.gz,$(HELM_SHA_$(PLATFORM)),$@)
	tar -xzf $@.download -O $(PLATFORM)/helm > $@ && chmod +x $@ && rm $@.download

$(KIND):
	$(call fetch,https://github.com/kubernetes-sigs/kind/releases/download/v$(KIND_VERSION)/kind-$(PLATFORM),$(KIND_SHA_$(PLATFORM)),$@)
	mv $@.download $@ && chmod +x $@

$(KUBECTL):
	$(call fetch,https://dl.k8s.io/release/v$(KUBECTL_VERSION)/bin/$(OS)/$(ARCH)/kubectl,$(KUBECTL_SHA_$(PLATFORM)),$@)
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

# the image this commit builds, on a kind cluster that exists only for the test
E2E = cd service && SYMPOSIUM_DATA_TEST_IMAGE=$(IMAGE):$(TAG) SYMPOSIUM_K8S_CHART=$(CURDIR)/$(PACKAGE) \
	SYMPOSIUM_K8S_HELM=$(CURDIR)/$(HELM) SYMPOSIUM_K8S_KIND=$(CURDIR)/$(KIND) \
	SYMPOSIUM_K8S_KUBECTL=$(CURDIR)/$(KUBECTL) $(UV) pytest tests/k8s

helm-e2e: build-docker k8s-tools helm-package
	$(E2E)
