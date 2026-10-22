"""Baseline single-core RV64GC O3 system for gem5 (SE mode).

Usage:
  build/RISCV/gem5.opt configs/riscv/o3_cpu.py --cmd path/to/static_rv64_binary \
      [--options "args"] [--core boom|p870] [--defense baseline] [--max-insts N]

Run from the gem5 tree (or pass --outdir via gem5's -d). The repo configs dir is
added to sys.path so this file works regardless of the working directory.
"""
import argparse
import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import m5
from m5.objects import (
    AddrRange, BiModeBP, Cache, L2XBar, LTAGE, Process, RiscvO3CPU, Root, SEWorkload,
    SimpleMemory, SrcClockDomain, System, SystemXBar, TournamentBP, VoltageDomain,
)

from common import default as BOOM
from common import p870 as P870

CORES = {"boom": BOOM, "p870": P870}

BPS = {"LTAGE": LTAGE, "Tournament": TournamentBP, "BiMode": BiModeBP}


class L1ICache(Cache):
    pass


class L1DCache(Cache):
    pass


class L2Cache(Cache):
    pass


def make_cache(cls, p):
    return cls(**p)


def build(args):
    D = CORES[args.core]
    system = System()
    system.clk_domain = SrcClockDomain(clock=D.CLOCK, voltage_domain=VoltageDomain())
    system.mem_mode = "timing"
    system.mem_ranges = [AddrRange(D.MEM_SIZE)]

    cpu = RiscvO3CPU(**D.CORE)
    cpu.branchPred = BPS[args.bp or D.BRANCH_PRED]()
    if hasattr(D, "RAS_SIZE"):
        cpu.branchPred.ras.numEntries = D.RAS_SIZE
    system.cpu = cpu

    # Caches
    cpu.icache = make_cache(L1ICache, D.CACHE["l1i"])
    cpu.dcache = make_cache(L1DCache, D.CACHE["l1d"])
    cpu.icache.cpu_side = cpu.icache_port
    cpu.dcache.cpu_side = cpu.dcache_port

    system.l2bus = L2XBar()
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

    cpu.createInterruptController()
    return system, cpu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", required=True, help="static RV64 ELF to run")
    ap.add_argument("--options", default="", help="arguments to the binary")
    ap.add_argument("--defense", default="baseline", choices=["baseline"])
    ap.add_argument("--core", default="boom", choices=sorted(CORES))
    ap.add_argument("--bp", default=None, choices=sorted(BPS), help="default: core's predictor")
    ap.add_argument("--max-insts", type=int, default=0, help="stop after N committed insts (0=run to exit)")
    args = ap.parse_args()

    system, cpu = build(args)

    mod = {"baseline": "no_defense"}[args.defense]
    importlib.import_module("defenses." + mod).apply(system, cpu)

    system.workload = SEWorkload.init_compatible(args.cmd)
    process = Process(cmd=[args.cmd] + args.options.split())
    cpu.workload = process
    cpu.createThreads()
    if args.max_insts:
        cpu.max_insts_any_thread = args.max_insts

    root = Root(full_system=False, system=system)
    m5.instantiate()
    print(f"Running {args.cmd} on RV64GC O3 ({args.core}, {args.defense}, bp={args.bp})")
    ev = m5.simulate()
    print(f"Exited @ tick {m5.curTick()}: {ev.getCause()}")


main()
