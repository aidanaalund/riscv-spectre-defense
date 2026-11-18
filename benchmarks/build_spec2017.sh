#!/usr/bin/env bash
# Cross-compile the SPEC CPU2017 benchmarks present under benchmarks/spec2017/
# into static RV64GC ELFs for gem5 SE mode.
#
# Layout expected per benchmark (see spec2017/MANIFEST.json):
#   benchmarks/spec2017/<name>/src/   SPEC sources
#   benchmarks/spec2017/<name>/run/   test (or train) input files
# Output:
#   benchmarks/bin/spec/<name>        the binary
#   benchmarks/bin/spec/<name>.run    argv, one token per line (run dir = run/)
#
# Benchmarks whose directory is missing are skipped, so this is safe to run
# before any SPEC sources have been added.
set -uo pipefail
cd "$(dirname "$0")"

SPEC_DIR=spec2017
OUT=bin/spec
MANIFEST=$SPEC_DIR/MANIFEST.json

[ -f "$MANIFEST" ] || { echo "no $MANIFEST; nothing to do"; exit 0; }

CC="${CC:-riscv64-linux-gnu-gcc}"
CXX="${CXX:-riscv64-linux-gnu-g++}"

# -O2 -static: gem5 SE mode needs static binaries. SPEC's own portability
# macros are passed per benchmark from the manifest.
COMMON="-O2 -static -march=rv64gc -fno-strict-aliasing -DSPEC -DSPEC_CPU -DNDEBUG"
CFLAGS="$COMMON -std=gnu99"
CXXFLAGS="$COMMON -std=c++14"

mkdir -p "$OUT"

names=$(python3 -c '
import json,sys
m=json.load(open(sys.argv[1]))
print("\n".join(k for k in m if not k.startswith("_")))' "$MANIFEST")

built=0 skipped=0
for name in $names; do
    src="$SPEC_DIR/$name/src"
    if [ ! -d "$src" ]; then
        echo "skip $name (no $src)"
        skipped=$((skipped+1))
        continue
    fi

    read -r lang extra < <(python3 -c '
import json,sys
b=json.load(open(sys.argv[1]))[sys.argv[2]]
print(b.get("lang","c"), " ".join(b.get("cflags",[])))' "$MANIFEST" "$name")

    # SPEC ships per-benchmark "specrand" helpers and sometimes nested dirs;
    # compile every source under src/, minus obvious non-build dirs.
    mapfile -t sources < <(find "$src" \
        \( -name '*.c' -o -name '*.cc' -o -name '*.cpp' -o -name '*.C' \) \
        -not -path '*/CVS/*' -not -path '*/.svn/*' | sort)

    if [ ${#sources[@]} -eq 0 ]; then
        echo "skip $name (no sources under $src)"
        skipped=$((skipped+1))
        continue
    fi

    # Headers can live in src/ or src/include/.
    incs="-I$src"
    [ -d "$src/include" ] && incs="$incs -I$src/include"

    if [ "$lang" = "cpp" ]; then
        tool="$CXX"; flags="$CXXFLAGS"
    else
        tool="$CC"; flags="$CFLAGS"
    fi

    echo "building $name (${#sources[@]} sources, $lang)"
    if ! $tool $flags $extra $incs "${sources[@]}" -lm -o "$OUT/$name" \
            2> "$OUT/$name.buildlog"; then
        echo "  FAILED -- see $OUT/$name.buildlog (last lines:)"
        tail -5 "$OUT/$name.buildlog" | sed 's/^/    /'
        skipped=$((skipped+1))
        continue
    fi

    python3 -c '
import json,sys
b=json.load(open(sys.argv[1]))[sys.argv[2]]
open(sys.argv[3],"w").write("\n".join(b.get("run",[]))+"\n")' \
        "$MANIFEST" "$name" "$OUT/$name.run"
    built=$((built+1))
done

echo "---"
echo "spec2017: $built built, $skipped skipped -> $OUT"
