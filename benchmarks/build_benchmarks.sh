#!/usr/bin/env bash
# Build the RV64GC Spectre-defense benchmarks as static ELFs for gem5 SE mode.
set -euo pipefail
cd "$(dirname "$0")"

CC="${CC:-riscv64-linux-gnu-gcc}"
# rv64gc + Zicbom (cbo.flush). -static for gem5 SE mode. -O2 so the Spectre
# gadget actually gets a speculation window; -fno-tree-vectorize keeps the
# probe loops simple.
CFLAGS="-O2 -static -march=rv64gc_zicbom -fno-stack-protector -fno-tree-vectorize"
OUT=bin
mkdir -p "$OUT"

echo "CC = $CC"
$CC --version | head -1

# Channel self-test
$CC $CFLAGS custom/flush_reload_rv.c -o "$OUT/flush_reload_rv"
echo "built $OUT/flush_reload_rv"

# Spectre v1 — baseline (no defense) and lfence (defense) from one source.
# Two training schedules: periodic (simple; beats history-free predictors) and
# randomized run-length (-DRAND_TRAIN; aperiodic, defeats LTAGE). Each crossed
# with the spec.fence defense (-DUSE_LFENCE) -> 4 Spectre binaries.
$CC $CFLAGS                          spectre_poc/spectre_v1_rv.c -o "$OUT/spectre_v1_rv"
echo "built $OUT/spectre_v1_rv (baseline, periodic)"
$CC $CFLAGS -DUSE_LFENCE             spectre_poc/spectre_v1_rv.c -o "$OUT/spectre_v1_rv_lfence"
echo "built $OUT/spectre_v1_rv_lfence (defense, periodic)"
$CC $CFLAGS -DRAND_TRAIN             spectre_poc/spectre_v1_rv.c -o "$OUT/spectre_v1_rv_rand"
echo "built $OUT/spectre_v1_rv_rand (baseline, randomized run-length)"
$CC $CFLAGS -DRAND_TRAIN -DUSE_LFENCE spectre_poc/spectre_v1_rv.c -o "$OUT/spectre_v1_rv_rand_lfence"
echo "built $OUT/spectre_v1_rv_rand_lfence (defense, randomized run-length)"

echo "---"
file "$OUT"/* 2>/dev/null || ls -l "$OUT"
