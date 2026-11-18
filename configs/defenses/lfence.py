"""lfence defense hook.

IMPORTANT: the actual Spectre defense for this project lives in the *binary*,
not here. The `spec.fence` speculation barrier is a custom-0 RISC-V instruction
(see benchmarks/riscv_asm.h + the gem5 decoder patch); the defended workload is
built with -DUSE_LFENCE (PoCs) or with spec.fence inserted after every
conditional branch (benchmarks). The O3 core needs no reconfiguration to honor
it -- the decoder patch already gives the instruction its
IsSerializeAfter|IsNonSpeculative semantics.

This hook therefore only tags the run and leaves the cores unchanged.
"""


def apply(system, cpus, args):
    """No microarchitectural change: the barrier is in the workload binary."""
    return
