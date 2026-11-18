"""RV64GC O3 system for gem5 (SE mode), 1..N cores with private L1s and a
shared L2.

Usage:
  build/RISCV/gem5.opt configs/riscv/o3_cpu.py --cmd path/to/static_rv64_binary \
      [--options "args"] [--core boom|p870] [--defense baseline|lfence|spt]
      [--num-cpus N] [--max-insts N] [--spt-untaint bwd ...]

Multi-core (--num-cpus > 1) runs ONE multi-threaded process: the main thread
starts on cpu0 and each pthread_create()d thread is placed on the next free
core (gem5 SE emulates clone/futex; affinity syscalls are no-ops). That is
what the cross-core Spectre PoC needs: victim and attacker on different cores
sharing only the L2.

Run from anywhere; the repo configs dir is added to sys.path.
"""
import argparse
import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import m5
from m5.objects import (
    AddrRange, BiModeBP, BranchPredictor, Cache, IQUnit, L2XBar, LTAGE, Process, RiscvO3CPU,
    Root, SEWorkload,
    SimpleMemory, SrcClockDomain, System, SystemXBar, TournamentBP, VoltageDomain,
)

from common import default as BOOM
from common import p870 as P870

CORES = {"boom": BOOM, "p870": P870}

BPS = {"LTAGE": LTAGE, "Tournament": TournamentBP, "BiMode": BiModeBP}

# --defense name -> module in configs/defenses/. Each module exposes
# add_args(parser) (optional) and apply(system, cpus, args).
DEFENSES = {"baseline": "no_defense", "lfence": "lfence",
            "fence": "fence", "spt": "spt"}


class L1ICache(Cache):
    pass


class L1DCache(Cache):
    pass


class L2Cache(Cache):
    pass


def make_cache(cls, p):
    return cls(**p)


def make_cpu(D, args, cpu_id):
    core_params = dict(D.CORE)
    for kv in args.set:                      # --set key=val core overrides
        k, v = kv.split("=", 1)
        core_params[k] = int(v) if v.lstrip("-").isdigit() else v
    # gem5 v25.1 moved the instruction-queue size out of the CPU and into a
    # vector of IQUnit SimObjects, so numIQEntries is applied separately.
    num_iq = core_params.pop("numIQEntries", None)
    cpu = RiscvO3CPU(cpu_id=cpu_id, **core_params)
    if num_iq is not None:
        cpu.instQueues = [IQUnit(numEntries=num_iq)]
    # gem5 v25.1 split the predictor: a BranchPredictor (BPU) wrapper holds a
    # pluggable conditionalBranchPred algorithm (LTAGE/Tournament/BiMode).
    # instShiftAmt=1 for RISC-V (2-byte min instruction alignment with RVC).
    cond_pred = BPS[args.bp or D.BRANCH_PRED]()
    cpu.branchPred = BranchPredictor(instShiftAmt=1, conditionalBranchPred=cond_pred)
    if hasattr(D, "RAS_SIZE"):
        cpu.branchPred.ras.numEntries = D.RAS_SIZE
    return cpu


def build(args):
    D = CORES[args.core]
    system = System()
    system.clk_domain = SrcClockDomain(clock=D.CLOCK, voltage_domain=VoltageDomain())
    system.mem_mode = "timing"
    system.mem_ranges = [AddrRange(D.MEM_SIZE)]

    cpus = [make_cpu(D, args, i) for i in range(args.num_cpus)]
    system.cpu = cpus

    # Private L1I/L1D per core -> coherent L2 crossbar -> shared L2.
    system.l2bus = L2XBar()
    for cpu in cpus:
        cpu.icache = make_cache(L1ICache, D.CACHE["l1i"])
        cpu.dcache = make_cache(L1DCache, D.CACHE["l1d"])
        cpu.icache.cpu_side = cpu.icache_port
        cpu.dcache.cpu_side = cpu.dcache_port
        cpu.icache.mem_side = system.l2bus.cpu_side_ports
        cpu.dcache.mem_side = system.l2bus.cpu_side_ports
    system.l2cache = make_cache(L2Cache, D.CACHE["l2"])
    system.l2cache.cpu_side = system.l2bus.mem_side_ports

    system.membus = SystemXBar()
    system.l2cache.mem_side = system.membus.cpu_side_ports

    # Memory: fixed-latency so L1 hit vs. DRAM miss gap is large and stable
    system.mem_ctrl = SimpleMemory(latency=D.MEM_LATENCY, bandwidth="12.8GB/s",
                                   range=system.mem_ranges[0])
    system.mem_ctrl.port = system.membus.mem_side_ports
    system.system_port = system.membus.cpu_side_ports

    for cpu in cpus:
        cpu.createInterruptController()
    return system, cpus


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", required=True, help="static RV64 ELF to run")
    ap.add_argument("--options", default="", help="arguments to the binary")
    ap.add_argument("--defense", default="baseline", choices=sorted(DEFENSES))
    ap.add_argument("--core", default="boom", choices=sorted(CORES))
    ap.add_argument("--num-cpus", type=int, default=1,
                    help="cores (threads of the one process spread across them)")
    ap.add_argument("--bp", default=None, choices=sorted(BPS), help="default: core's predictor")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VAL",
                    help="override a core parameter (repeatable)")
    ap.add_argument("--max-insts", type=int, default=0, help="stop after N committed insts (0=run to exit)")
    ap.add_argument("--input", default=None, help="file to connect to the program's stdin")
    ap.add_argument("--cwd", default=None, help="working directory of the simulated process "
                    "(SPEC run dirs with input files); default: gem5's cwd")
    mods = {name: importlib.import_module("defenses." + m) for name, m in DEFENSES.items()}
    for m in mods.values():
        if hasattr(m, "add_args"):
            m.add_args(ap)
    args = ap.parse_args()

    system, cpus = build(args)
    mods[args.defense].apply(system, cpus, args)

    system.workload = SEWorkload.init_compatible(args.cmd)
    process = Process(cmd=[args.cmd] + args.options.split())
    if args.cwd:
        process.cwd = os.path.abspath(args.cwd)
    if args.input:
        process.input = args.input
    for cpu in cpus:
        cpu.workload = process
        cpu.createThreads()
        if args.max_insts:
            cpu.max_insts_any_thread = args.max_insts

    root = Root(full_system=False, system=system)
    m5.instantiate()
    print(f"Running {args.cmd} on RV64GC O3 ({args.core} x{args.num_cpus}, "
          f"{args.defense}, bp={args.bp})")
    ev = m5.simulate()
    print(f"Exited @ tick {m5.curTick()}: {ev.getCause()}")


main()
