#!/usr/bin/env bash
# Build the gem5 tree vendored in this repo (./gem5, which already carries the
# project's RISC-V changes: spec.fence decode + U-mode Zicbom enable) INSIDE the
# container (see docker/README.md's `make docker-shell`).
#
# The repo is bind-mounted at /work/repo, so the build lands in
# /work/repo/gem5/build (git-ignored by gem5/.gitignore). Edit gem5 sources in
# ./gem5 and re-run this script; scons is incremental.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/work/repo}"
GEM5_DIR="${GEM5_DIR:-$REPO_DIR/gem5}"
JOBS="${JOBS:-$(nproc)}"

echo "== gem5 build =="
echo "   src   : $GEM5_DIR"
echo "   CC    : ${CC:-cc}  CXX: ${CXX:-c++}  (-j$JOBS)"

cd "$GEM5_DIR"

# Clean stale protobuf artifacts (a known build-breaker if an older protoc ran).
rm -f build/RISCV/proto/*.pb.h build/RISCV/proto/*.pb.cc 2>/dev/null || true

echo "-- building gem5.opt"
scons build/RISCV/gem5.opt -j"$JOBS" --ignore-style

echo
echo "== done: $GEM5_DIR/build/RISCV/gem5.opt =="
echo "Run experiments with:  GEM5=$GEM5_DIR/build/RISCV/gem5.opt make experiment"
