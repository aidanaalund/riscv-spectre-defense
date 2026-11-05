GEM5 ?= $(HOME)/Applications/gem5/build/RISCV/gem5.opt

build-gem5:
	cd $(HOME)/Applications/gem5 && scons build/RISCV/gem5.opt -j$(shell nproc)

build-benchmarks:
	benchmarks/build_benchmarks.sh

# Quick single run: channel self-test on the BOOM-like core
self-test: build-benchmarks
	$(GEM5) configs/riscv/o3_cpu.py --core boom --cmd benchmarks/bin/flush_reload_rv

# Full matrix: {boom,p870} x {self-test, baseline, lfence}
experiment: build-benchmarks
	python3 scripts/run_experiment.py

plot:
	python3 scripts/plot_results.py

# --- Docker dev environment (see docker/README.md) ---
DOCKER_IMAGE ?= riscv-spectre-dev
GEM5_VOLUME  ?= riscv-spectre-gem5

# Build the toolchain image, tagged with your UID/GID so mounted files stay yours.
docker-build:
	docker build -t $(DOCKER_IMAGE) \
	  --build-arg UID=$(shell id -u) --build-arg GID=$(shell id -g) \
	  docker

# Interactive shell: this repo at /work/repo, a persistent gem5 build at /work/gem5.
docker-shell:
	docker run --rm -it \
	  -v $(CURDIR):/work/repo \
	  -v $(GEM5_VOLUME):/work/gem5 \
	  $(DOCKER_IMAGE)

.PHONY: build-gem5 build-benchmarks self-test experiment plot docker-build docker-shell
