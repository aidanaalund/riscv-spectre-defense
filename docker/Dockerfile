# gem5 RV64GC Spectre-defense dev environment.
#
# Thin layer on top of the OFFICIAL gem5 dependencies image. That base already
# provides gem5's full build stack on Ubuntu 24.04 with GCC 13.3 -- which is
# important: gem5 supports GCC 11-14.2, and a newer host GCC (e.g. GCC 16 on
# CachyOS) MISCOMPILES gem5's O3 CPU model so the simulator faults on every
# program. Building inside this image sidesteps that with no host setup.
#
# We add only what the base lacks for THIS project:
#   - the riscv64-linux-gnu cross compiler (to build the rv64gc benchmarks)
#   - matplotlib + numpy (for scripts/plot_results.py)
#
# The image is toolchain only; it does NOT bake in a built gem5 tree. Clone +
# patch + build gem5 into a mounted volume with docker/build-gem5.sh. See
# docker/README.md.
FROM ghcr.io/gem5/ubuntu-24.04_all-dependencies:latest

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc-riscv64-linux-gnu libc6-dev-riscv64-cross \
        python3-matplotlib python3-numpy \
        file less vim \
    && rm -rf /var/lib/apt/lists/*

# NOTE: deliberately do NOT set ENV CC/CXX here. The base image's default gcc is
# already 13.3 (gem5-supported), and a global CC=gcc would hijack the benchmark
# cross-build (build_benchmarks.sh honours $CC, defaulting to riscv64-linux-gnu-gcc).
# build-gem5.sh picks the compiler for gem5's scons build itself.

# Run as a non-root user whose files on the mounted volume stay editable on the
# host. Override UID/GID at build time to match your host user:
#   docker build --build-arg UID=$(id -u) --build-arg GID=$(id -g) ...
ARG UID=1000
ARG GID=1000
RUN (getent group $GID || groupadd -g $GID dev) \
    && (id -u $UID >/dev/null 2>&1 || useradd -m -u $UID -g $GID -s /bin/bash dev)

# Create mount points owned by the dev user BEFORE dropping privileges, so a
# fresh named volume mounted at /work/gem5 inherits writable ownership.
RUN mkdir -p /work/gem5 /work/repo && chown -R $UID:$GID /work
USER $UID:$GID

WORKDIR /work/repo
CMD ["/bin/bash"]
