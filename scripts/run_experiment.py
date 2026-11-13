#!/usr/bin/env python3
"""Run the Spectre-v1 / lfence experiment matrix on gem5 and collect results.

Matrix: {boom, p870} x {self-test, spectre baseline, spectre lfence}.
For each run we capture gem5 stdout (the PoC prints its recovered string and
accuracy) and the stats.txt (sim cycles / committed insts), and fold everything
into results/results.json for scripts/plot_results.py and the paper.

Usage:
    python3 scripts/run_experiment.py [--cores boom p870] [--sweep] [--jobs N]
Env:
    GEM5   path to gem5.opt (default ~/Applications/gem5/build/RISCV/gem5.opt)
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEM5 = os.environ.get("GEM5",
                      os.path.expanduser("~/Applications/gem5/build/RISCV/gem5.opt"))
CONFIG = os.path.join(ROOT, "configs", "riscv", "o3_cpu.py")
BIN = os.path.join(ROOT, "benchmarks", "bin")
RESULTS = os.path.join(ROOT, "results")

# Each run: (name, binary, defense-flag, branch-predictor, poc?).
# All runs use the core's default predictor, LTAGE (bp=None).
RUNS = [
    ("self_test",          "flush_reload_rv",      "baseline", None,      False),
    # Naive periodic mistraining. (An earlier host-built binary leaked only 1/8
    # here; that was layout-dependent aliasing -- rebuilt binaries leak 8/8.)
    ("spectre_base_ltage", "spectre_v1_rv",        "baseline", None,      True),
    ("spectre_lfence_ltage","spectre_v1_rv_lfence","lfence",   None,      True),
    # Randomized run-length + history-decorrelation mistraining (robust
    # against LTAGE learning the schedule). spec.fence still blocks it.
    ("spectre_rand_ltage",       "spectre_v1_rv_rand",        "baseline", None,     True),
    ("spectre_rand_lfence_ltage","spectre_v1_rv_rand_lfence", "lfence",   None,     True),
]


# Speculation-window sweep (--sweep): the baseline periodic PoC with N nops
# between the bounds check and the gadget load (benchmarks/bin/pad/), under
# the core's default LTAGE. Only the window closing should stop the leak.
SWEEP_BP = None


def sweep_runs():
    d = os.path.join(BIN, "pad")
    if not os.path.isdir(d):
        return []
    pads = sorted(int(f[len("spectre_v1_rv_pad"):]) for f in os.listdir(d)
                  if f.startswith("spectre_v1_rv_pad"))
    return [(f"pad{n}", os.path.join("pad", f"spectre_v1_rv_pad{n}"),
             "baseline", SWEEP_BP, True, n) for n in pads]


def run_one(core, name, binary, defense, bp, outdir):
    os.makedirs(outdir, exist_ok=True)
    cmd = [GEM5, "-d", outdir, CONFIG,
           "--core", core, "--defense", defense,
           "--cmd", os.path.join(BIN, binary)]
    if bp:
        cmd += ["--bp", bp]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    stdout = p.stdout + p.stderr
    with open(os.path.join(outdir, "sim.out"), "w") as f:
        f.write(stdout)
    return stdout, parse_stats(os.path.join(outdir, "stats.txt"))


def parse_stats(path):
    want = {"simTicks": None, "numCycles": None,
            "committedInsts": None, "ipc": None}
    if not os.path.exists(path):
        return want
    with open(path) as f:
        for line in f:
            m = re.match(r"(\S+)\s+([\d.]+)", line)
            if not m:
                continue
            k, v = m.group(1), m.group(2)
            if k.endswith("simTicks"):
                want["simTicks"] = float(v)
            elif k.endswith("numCycles"):
                want["numCycles"] = float(v)
            elif k.endswith("committedInsts") and want["committedInsts"] is None:
                want["committedInsts"] = float(v)
            elif k.endswith("ipc") and want["ipc"] is None:
                want["ipc"] = float(v)
    return want


def parse_poc(stdout):
    """Pull recovered string, accuracy, threshold, and per-char best hits."""
    out = {"expected": None, "recovered": None, "accuracy": None,
           "threshold": None, "hit_cyc": None, "miss_cyc": None,
           "per_char": []}
    m = re.search(r"Avg hit:\s*(\d+).*?miss:\s*(\d+).*?threshold:\s*(\d+)", stdout)
    if m:
        out["hit_cyc"], out["miss_cyc"], out["threshold"] = map(int, m.groups())
    m = re.search(r"Expected\s*:\s*(.+)", stdout)
    if m:
        out["expected"] = m.group(1).strip()
    m = re.search(r"Recovered:\s*(.*)", stdout)
    if m:
        out["recovered"] = m.group(1).strip()
    m = re.search(r"Accuracy\s*:\s*(\d+)/(\d+)", stdout)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        out["accuracy"] = {"correct": a, "total": b,
                           "frac": (a / b if b else 0.0)}
    for mm in re.finditer(r"best='(.)' \(0x([0-9a-f]+), hits=(\d+)\)", stdout):
        out["per_char"].append({"char": mm.group(1),
                                "byte": int(mm.group(2), 16),
                                "hits": int(mm.group(3))})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cores", nargs="+", default=["boom"], choices=["boom", "p870"])
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1,
                    help="parallel gem5 processes")
    ap.add_argument("--sweep", action="store_true",
                    help="also run the speculation-window pad sweep")
    ap.add_argument("--sweep-only", action="store_true",
                    help="run only the pad sweep")
    ap.add_argument("--only", nargs="+", default=None,
                    help="subset of workload names to run")
    args = ap.parse_args()

    if not os.path.exists(GEM5):
        sys.exit(f"gem5 not found at {GEM5}; set $GEM5")
    if not os.path.isdir(BIN):
        sys.exit(f"benchmarks not built: {BIN} missing. "
                 f"Run benchmarks/build_benchmarks.sh")

    jobs = []
    for core in args.cores:
        todo = [] if args.sweep_only else [r + (None,) for r in RUNS]
        if args.sweep or args.sweep_only:
            todo += sweep_runs()
        for name, binary, defense, bp, is_poc, pad in todo:
            if args.only and name not in args.only:
                continue
            jobs.append((core, name, binary, defense, bp, is_poc, pad))

    def work(job):
        core, name, binary, defense, bp, is_poc, pad = job
        outdir = os.path.join(RESULTS, core, name)
        stdout, stats = run_one(core, name, binary, defense, bp, outdir)
        rec = {"core": core, "workload": name, "binary": binary,
               "defense": defense, "bp": bp or "LTAGE", "stats": stats}
        if pad is not None:
            rec["pad"] = pad
        m = re.search(r"Exited @ tick \d+: (.*)", stdout)
        rec["exit"] = m.group(1).strip() if m else "CRASH/NO-EXIT"
        if is_poc:
            rec["poc"] = parse_poc(stdout)
            acc = rec["poc"].get("accuracy")
            tag = f"{acc['correct']}/{acc['total']}" if acc else "?"
            msg = (f"recovered {rec['poc'].get('recovered')!r} accuracy {tag}")
        else:
            rec["self_test"] = ("CHANNEL OK" in stdout)
            msg = f"channel {'OK' if rec['self_test'] else 'FAIL'}"
        print(f"[{core}] {name} (bp={bp or 'default'}) -> {msg}  "
              f"[{rec['exit']}]", flush=True)
        return rec

    with cf.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        new = list(ex.map(work, jobs))

    # Merge into any existing results.json so per-core / sweep invocations
    # accumulate instead of clobbering each other.
    path = os.path.join(RESULTS, "results.json")
    results = {"gem5": GEM5, "runs": []}
    if os.path.exists(path):
        with open(path) as f:
            results["runs"] = json.load(f).get("runs", [])
    key = lambda r: (r["core"], r["workload"])
    fresh = {key(r) for r in new}
    results["runs"] = [r for r in results["runs"] if key(r) not in fresh] + new

    os.makedirs(RESULTS, exist_ok=True)
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
