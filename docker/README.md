# Docker dev environment

A reproducible, host-independent environment for building gem5 and running the
RV64GC Spectre-defense experiments. It is a **thin layer on the official
`ghcr.io/gem5/ubuntu-24.04_all-dependencies` image** (GCC 13.3 + gem5's full
build stack), adding only what this project needs that the base lacks: the
`riscv64-linux-gnu` cross compiler (+ its target libc) and matplotlib/numpy.

Use it to avoid setting up the toolchain by hand — **especially** because on
recent distros the system GCC (e.g. GCC 16) miscompiles gem5's O3 CPU model and
the simulator then faults on every program. The base image's GCC 13.3 is in
gem5's supported range (11–14.2), so building gem5 here sidesteps that entirely.

## What's in the image vs. what you build

The image has only the **toolchain + dependencies** (the official gem5 build
deps, plus the `riscv64-linux-gnu` cross compiler and the Python plotting stack
this layer adds). It does **not** contain a built gem5 — that lives in a Docker **named volume**
(`riscv-spectre-gem5`, mounted at `/work/gem5`) so the ~GB build persists across
runs and never bloats the image or goes stale against the patches.

This repo is mounted read-write at `/work/repo`, so edits you make inside the
container are your real working tree.

## Quick start

```bash
# 1. Build the image (tagged with your host UID/GID so files stay yours)
make docker-build

# 2. Open a shell in the container (repo + a persistent gem5 volume mounted)
make docker-shell

# --- now inside the container ---

# 3. Clone + patch + build gem5 into the volume (first time: ~minutes).
#    Idempotent; re-run anytime to rebuild after changing a patch.
docker/build-gem5.sh

# 4. Build the benchmarks and run the experiment matrix
make build-benchmarks
GEM5=/work/gem5/build/RISCV/gem5.opt make experiment
GEM5=/work/gem5/build/RISCV/gem5.opt make self-test   # quick sanity run
make plot
```

`GEM5=/work/gem5/build/RISCV/gem5.opt` points the Makefile/scripts at the gem5
you just built in the volume (the default path is the host layout
`~/Applications/gem5/...`, which doesn't exist in the container).

## Notes

- **Compiler.** The image pins `CC=gcc-13 CXX=g++-13`. Do not override these
  with a newer GCC — gem5 supports 11–14.2 only, and newer compilers produce a
  gem5 binary that faults at runtime. `docker/build-gem5.sh` honours `$CC`/`$CXX`.
- **gem5 version.** `build-gem5.sh` checks out tag `v25.1.0.1`, the exact tag the
  patches in `patches/` were generated against. Override with
  `GEM5_TAG=... docker/build-gem5.sh` at your own risk.
- **Sharing the build across teammates.** The gem5 volume is per-machine. Each
  teammate runs `docker/build-gem5.sh` once. The *image* (toolchain) is the
  shareable, reproducible part; push it to a registry if you want to skip the
  apt install.
- **Rebuilding gem5 after editing a patch.** Re-run `docker/build-gem5.sh` — it
  re-applies the patch if needed and does an incremental scons build.
