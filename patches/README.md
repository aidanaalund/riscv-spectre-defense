# gem5 patches

Microarchitectural changes to gem5 required by this project. Generated against
gem5 **v25.1.0.1** (`v25.1.0.1-13-gf5c5a6e390`).

## Apply

```bash
cd /path/to/gem5
git apply /path/to/riscv-spectre-defense/patches/gem5_spectre_defense.patch
scons build/RISCV/gem5.opt -j$(nproc)
```

## `gem5_spectre_defense.patch`

Two changes to the RISC-V O3 model:

1. **`src/arch/riscv/process.cc`** — in `RiscvProcess64::initState`, set
   `senvcfg.{CBCFE,CBIE,CBZE}` so Zicbom cache-block ops (`cbo.flush`) are
   permitted from user mode in SE mode. Without this a user-mode `cbo.flush`
   raises an illegal-instruction fault, so the Flush+Reload channel can't flush.

2. **`src/arch/riscv/isa/decoder.isa`** — add `spec_fence`, a custom-0
   (major opcode `0x0b`, funct3=0) speculation barrier. Flags
   `IsSerializeAfter | IsNonSpeculative` make the O3 core execute it only at the
   ROB head and stall the following instruction until it commits, giving an
   x86-`lfence`-like barrier RISC-V otherwise lacks. Encoded in the benchmarks
   via `.insn r 0x0b,0,0,x0,x0,x0` (see `benchmarks/riscv_asm.h`).

The repo's `src/` tree mirrors the patched regions for reference; the patch is
the source of truth.
