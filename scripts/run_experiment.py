#!/usr/bin/env python3
"""Run the Spectre-v1 / lfence experiment matrix on gem5 and collect results.

Matrix: {boom, p870} x {self-test, spectre baseline, spectre lfence}.
For each run we capture gem5 stdout (the PoC prints its recovered string and
accuracy) and the stats.txt (sim cycles / committed insts), and fold everything
into results/results.json for scripts/plot_results.py and the paper.

Usage:
    python3 scripts/run_experiment.py [--cores boom p870] [--quick]
Env:
    GEM5   path to gem5.opt (default ~/Applications/gem5/build/RISCV/gem5.opt)
"""
import argparse
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
# We sweep the predictor because a strong TAGE-class predictor (LTAGE) learns
# the naive periodic mistraining and resists the PoC, whereas simpler
# predictors (Tournament) leak fully — both are interesting for the paper.
# bp=None means use the core's default predictor (LTAGE).
RUNS = [
    ("self_test",          "flush_reload_rv",      "baseline", None,      False),
    # Headline: a simple bimodal predictor can't learn the periodic training,
    # so the baseline leaks the full secret reproducibly and spec.fence blocks it.
    ("spectre_base_bimode", "spectre_v1_rv",       "baseline", "BiMode",  True),
    ("spectre_lfence_bimode","spectre_v1_rv_lfence","lfence",  "BiMode",  True),
    # Finding: stronger global-history predictors learn the period and resist
    # the naive PoC, leaking only a prefix. bp=None uses the core default (LTAGE).
    ("spectre_base_ltage", "spectre_v1_rv",        "baseline", None,      True),
    ("spectre_lfence_ltage","spectre_v1_rv_lfence","lfence",   None,      True),
    # Result: randomized run-length (aperiodic) mistraining defeats LTAGE --
    # with no period to tag, LTAGE falls back to its base predictor and
    # mispredicts, so the leak is recovered under the core's own default
    # predictor. The spec.fence defense still blocks it to 0/N.
    ("spectre_rand_ltage",       "spectre_v1_rv_rand",        "baseline", None,     True),
    ("spectre_rand_lfence_ltage","spectre_v1_rv_rand_lfence", "lfence",   None,     True),
]


def run_one(core, name, binary, defense, bp, outdir):
    os.makedirs(outdir, exist_ok=True)
    cmd = [GEM5, "-d", outdir, CONFIG,
           "--core", core, "--defense", defense,
           "--cmd", os.path.join(BIN, binary)]
    if bp:
        cmd += ["--bp", bp]
    print("  $", " ".join(cmd))
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
    ap.add_argument("--cores", nargs="+", default=["boom"],
                    help="p870 currently triggers a gem5 O3 instability (see docs)")
    ap.add_argument("--only", nargs="+", default=None,
                    help="subset of workload names to run")
    args = ap.parse_args()

    if not os.path.exists(GEM5):
        sys.exit(f"gem5 not found at {GEM5}; set $GEM5")
    if not os.path.isdir(BIN):
        sys.exit(f"benchmarks not built: {BIN} missing. "
                 f"Run benchmarks/build_benchmarks.sh")

    results = {"gem5": GEM5, "runs": []}
    for core in args.cores:
        for name, binary, defense, bp, is_poc in RUNS:
            if args.only and name not in args.only:
                continue
            print(f"[{core}] {name} ({binary}, bp={bp or 'default'})")
            outdir = os.path.join(RESULTS, core, name)
            stdout, stats = run_one(core, name, binary, defense, bp, outdir)
            rec = {"core": core, "workload": name, "binary": binary,
                   "defense": defense, "bp": bp or "LTAGE", "stats": stats}
            if is_poc:
                rec["poc"] = parse_poc(stdout)
                acc = rec["poc"].get("accuracy")
                tag = f"{acc['correct']}/{acc['total']}" if acc else "?"
                print(f"    -> recovered {rec['poc'].get('recovered')!r} "
                      f"accuracy {tag}")
            else:
                rec["self_test"] = ("CHANNEL OK" in stdout)
                print(f"    -> channel {'OK' if rec['self_test'] else 'FAIL'}")
            results["runs"].append(rec)

    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "results.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
