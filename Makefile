# RISC-V Spectre Defense project: experiment and build harness
#
#   make help              list targets
#   make gem5              build gem5 (incremental)
#   make benchmarks        cross-compile PoCs + SPEC CPU2017 (if present)
#   make poc               security check: all defenses vs. the Spectre PoCs
#   make perf              performance: all defenses x both cores on SPEC
#   make plot              figures from results/results.json
#
# Common overrides:
#   JOBS=4                 parallelism (scons -j and parallel gem5 runs)
#   CORES="boom p870"      which core models to sweep
#   DOCKER=0               run commands directly instead of in the container

SHELL := /bin/bash
REPO  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

# Docker Desktop's VM here has 8 CPUs / ~9.7 GB; keep JOBS modest or gem5
# builds and parallel O3 runs will OOM the VM.
JOBS  ?= 6
CORES ?= boom p870

DOCKER_IMAGE ?= riscv-spectre-dev
# Auto-detect: inside the container the repo is bind-mounted at /work/repo.
ifeq ($(wildcard /work/repo/Makefile),)
DOCKER ?= 1
else
DOCKER ?= 0
endif

ifeq ($(DOCKER),1)
RUN := docker run --rm -t -v "$(REPO)":/work/repo -w /work/repo $(DOCKER_IMAGE) bash -lc
GEM5_BIN := /work/repo/gem5/build/RISCV/gem5.opt
else
RUN := bash -lc
GEM5_BIN := $(REPO)/gem5/build/RISCV/gem5.opt
endif

# gem5 binary used by the run scripts (override to use a different build).
GEM5 ?= $(GEM5_BIN)
export GEM5

.DEFAULT_GOAL := help

# ---------------------------------------------------------------- help ----
.PHONY: help
help:
	@echo "Targets:"
	@sed -n 's/^\([a-z0-9-]*\):.*## \(.*\)/  \1|\2/p' $(MAKEFILE_LIST) \
	  | column -t -s'|'
	@echo
	@echo "DOCKER=$(DOCKER)  JOBS=$(JOBS)  CORES=$(CORES)"
	@echo "GEM5=$(GEM5)"

# --------------------------------------------------------------- build ----
.PHONY: gem5
gem5: ## Build gem5 (incremental; re-run after editing gem5/src)
	$(RUN) 'JOBS=$(JOBS) docker/build-gem5.sh'

.PHONY: gem5-clean
gem5-clean: ## Delete the gem5 build tree
	rm -rf $(REPO)/gem5/build

.PHONY: benchmarks
benchmarks: ## Cross-compile the PoCs and any SPEC CPU2017 sources present
	$(RUN) 'benchmarks/build_benchmarks.sh'
	$(RUN) 'benchmarks/build_spec2017.sh'

.PHONY: poc-bins
poc-bins: ## Cross-compile only the Spectre PoCs (fast)
	$(RUN) 'benchmarks/build_benchmarks.sh'

# --------------------------------------------------------- experiments ----
# Security: does each defense stop the leak? Runs the single-core v1 PoCs and
# the 2-core cross-core PoC under every defense.
.PHONY: poc
poc: ## Security matrix: every defense vs. the Spectre PoCs
	$(RUN) 'python3 scripts/run_experiment.py --suite poc \
	        --cores $(CORES) --jobs $(JOBS)'

# Performance: SPEC CPU2017 under every defense, both cores.
.PHONY: perf
perf: ## Performance matrix: every defense x core on SPEC CPU2017
	$(RUN) 'python3 scripts/run_experiment.py --suite spec \
	        --cores $(CORES) --jobs $(JOBS) --max-insts $(MAX_INSTS)'
MAX_INSTS ?= 200000000

.PHONY: sweep
sweep: ## Speculation-window sweep (pad N nops; baseline only)
	$(RUN) 'python3 scripts/run_experiment.py --suite sweep \
	        --cores $(CORES) --jobs $(JOBS)'

.PHONY: experiment
experiment: poc perf ## Both matrices (security + performance)

.PHONY: plot
plot: ## Regenerate figures from results/results.json
	$(RUN) 'python3 scripts/plot_results.py'

# Quick smoke test: one PoC run per defense on BOOM, nothing recorded.
.PHONY: smoke
smoke: ## Fast sanity check of the three defenses on one core
	$(RUN) 'python3 scripts/run_experiment.py --suite poc --cores boom \
	        --jobs $(JOBS) --only spectre_rand --dry-summary'

# -------------------------------------------------------------- docker ----
.PHONY: docker-build
docker-build: ## Build the toolchain image (tagged with your UID/GID)
	docker build -t $(DOCKER_IMAGE) \
	  --build-arg UID=$(shell id -u) --build-arg GID=$(shell id -g) \
	  $(REPO)/docker

.PHONY: docker-shell
docker-shell: ## Interactive shell in the container (repo at /work/repo)
	docker run --rm -it -v "$(REPO)":/work/repo -w /work/repo $(DOCKER_IMAGE)

# --------------------------------------------------------------- clean ----
.PHONY: clean
clean: ## Remove built benchmarks and simulation output
	rm -rf $(REPO)/benchmarks/bin $(REPO)/m5out
