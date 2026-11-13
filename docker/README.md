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
this layer adds). It does **not** contain a built gem5 — gem5 is vendored in this repo
(`./gem5`, v25.1.0.1 plus the project's changes) and builds into `./gem5/build`
(git-ignored), so the ~GB build persists on the host across container runs.

This repo is mounted read-write at `/work/repo`, so edits you make inside the
container are your real working tree.

## Quick start

```bash
# 1. Build the image (tagged with your host UID/GID so files stay yours)
make docker-build

# 2. Open a shell in the container (repo + a persistent gem5 volume mounted)
make docker-shell

# --- now inside the container ---

# 3. Build the gem5 vendored in this repo (./gem5, with the project's changes
#    already applied) into ./gem5/build. Incremental; re-run after editing
#    anything under gem5/src. Keep JOBS modest: Docker Desktop's VM can OOM.
JOBS=4 docker/build-gem5.sh

# 4. Build the benchmarks and run the experiment matrix (+ window sweep)
make build-benchmarks
GEM5=/work/repo/gem5/build/RISCV/gem5.opt python3 scripts/run_experiment.py \
    --cores boom p870 --sweep --jobs 6
make plot
```

`GEM5=/work/repo/gem5/build/RISCV/gem5.opt` points the scripts at the gem5 you
just built (the default path is the host layout `~/Applications/gem5/...`).

## Notes

- **Compiler.** The image pins `CC=gcc-13 CXX=g++-13`. Do not override these
  with a newer GCC — gem5 supports 11–14.2 only, and newer compilers produce a
  gem5 binary that faults at runtime. `docker/build-gem5.sh` honours `$CC`/`$CXX`.
- **gem5 changes** live directly in `./gem5/src` (spec.fence decode,
  U-mode Zicbom enable, and an O3 squash fix in `cpu/o3/commit.cc` +
  `cpu/o3/cpu.{hh,cc}` that makes the P870 config's 2-cycle
  `commitToFetchDelay` safe). Re-run `docker/build-gem5.sh` after editing.
- **Sharing the build across teammates.** Each teammate runs
  `docker/build-gem5.sh` once. The *image* (toolchain) is the shareable,
  reproducible part; push it to a registry if you want to skip the apt install.
