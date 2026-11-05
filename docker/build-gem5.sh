#!/usr/bin/env bash
# Clone, patch, and build gem5 INSIDE the container (run from docker/README.md's
# `make docker-shell`). gem5 lands in /work/gem5, which is a mounted volume, so
# the ~GB build persists across container restarts and is shared by the team.
#
# Idempotent: re-running rebuilds (scons is incremental) and re-applies the
# patch only if it isn't already applied.
set -euo pipefail

GEM5_DIR="${GEM5_DIR:-/work/gem5}"
GEM5_TAG="${GEM5_TAG:-v25.1.0.1}"      # the tag the patch was generated against
REPO_DIR="${REPO_DIR:-/work/repo}"     # this project, mounted read-write
PATCH="$REPO_DIR/patches/gem5_spectre_defense.patch"
JOBS="${JOBS:-$(nproc)}"

echo "== gem5 build =="
echo "   tag   : $GEM5_TAG"
echo "   dest  : $GEM5_DIR"
echo "   patch : $PATCH"
echo "   CC    : ${CC:-cc}  CXX: ${CXX:-c++}  (-j$JOBS)"

if [ ! -d "$GEM5_DIR/.git" ]; then
    echo "-- cloning gem5 $GEM5_TAG"
    git clone --depth 1 --branch "$GEM5_TAG" https://github.com/gem5/gem5.git "$GEM5_DIR"
fi

cd "$GEM5_DIR"

# Apply our two RISC-V patches if not already present.
if git apply --reverse --check "$PATCH" >/dev/null 2>&1; then
    echo "-- patch already applied"
else
    echo "-- applying $PATCH"
    git apply "$PATCH"
fi

# Clean stale protobuf artifacts (a known build-breaker if an older protoc ran).
rm -f build/RISCV/proto/*.pb.h build/RISCV/proto/*.pb.cc 2>/dev/null || true

echo "-- building gem5.opt"
scons build/RISCV/gem5.opt -j"$JOBS"

echo
echo "== done: $GEM5_DIR/build/RISCV/gem5.opt =="
echo "Run experiments with:  GEM5=$GEM5_DIR/build/RISCV/gem5.opt make experiment"
