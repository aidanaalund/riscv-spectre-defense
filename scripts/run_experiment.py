#!/usr/bin/env python3
"""Run the Spectre-defense experiment matrix on gem5 and collect results.

Three suites:

  poc    Security. Does the defense stop the leak? Runs the Spectre v1 PoCs
         (single core) and the cross-core PoC (2 cores) under every defense
         and records the recovered-byte accuracy. A defense "works" iff
         accuracy is 0/N while the baseline recovers the secret.

  spec   Performance. SPEC CPU2017 under every defense on every core model,
         capped at --max-insts committed instructions. Reports IPC relative
         to the undefended baseline.

  sweep  Speculation-window probe: the baseline PoC with N nops between the
         bounds check and the gadget load (benchmarks/bin/pad/).

Results accumulate in results/results.json for scripts/plot_results.py.

Usage:
    python3 scripts/run_experiment.py --suite poc  --cores boom p870
    python3 scripts/run_experiment.py --suite spec --cores boom p870 --jobs 6
Env:
    GEM5   path to gem5.opt (default: the repo build)
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEM5 = os.environ.get("GEM5", os.path.join(ROOT, "gem5", "build", "RISCV", "gem5.opt"))
CONFIG = os.path.join(ROOT, "configs", "riscv", "o3_cpu.py")
BIN = os.path.join(ROOT, "benchmarks", "bin")
SPEC_BIN = os.path.join(BIN, "spec")
RESULTS = os.path.join(ROOT, "results")

# ---------------------------------------------------------------- defenses --
# name -> (extra gem5 config args, binary-name suffix)
#
# "lfence" is the SOFTWARE spec.fence barrier: it needs a differently compiled
# binary, so it only applies to the PoCs (we have no compiler pass to insert
# barriers into SPEC). "fence" is its hardware stand-in -- delay every access
# to the visibility point -- and runs on unmodified binaries, so it is the
# defense used for the SPEC performance comparison.
DEFENSES = {
    "baseline": ([], ""),
    "lfence":   (["--defense", "lfence"], "_lfence"),
    "fence":    (["--defense", "fence"], ""),
    "spt":      (["--defense", "spt", "--spt-untaint", "bwd"], ""),
    # SPT ablations (paper configurations), all on unmodified binaries.
    "spt_none": (["--defense", "spt", "--spt-untaint", "none"], ""),
    "spt_fwd":  (["--defense", "spt", "--spt-untaint", "fwd"], ""),
    "spt_ideal": (["--defense", "spt", "--spt-untaint", "ideal"], ""),
}

# Defenses in the headline comparison (what the report's figures show).
MAIN_DEFENSES = ["baseline", "fence", "spt"]
POC_DEFENSES = ["baseline", "lfence", "fence", "spt"]

# PoC workloads: (name, binary stem, #cpus, is-poc)
POCS = [
    ("self_test",     "flush_reload_rv", 1, False),
    ("spectre_v1",    "spectre_v1_rv",   1, True),
    # Randomized run-length + history decorrelation: defeats LTAGE learning
    # the training schedule, so the baseline leak is robust.
    ("spectre_rand",  "spectre_v1_rv_rand", 1, True),
    ("spectre_cross", "cross_core_spectre_v1", 2, True),
]


def spec_workloads():
    """Built SPEC benchmarks, as (name, binary path, argv, run dir)."""
    out = []
    if not os.path.isdir(SPEC_BIN):
        return out
    for f in sorted(os.listdir(SPEC_BIN)):
        path = os.path.join(SPEC_BIN, f)
        runfile = path + ".run"
        if not os.path.isfile(runfile) or not os.access(path, os.X_OK):
            continue
        with open(runfile) as fh:
            argv = [ln.strip() for ln in fh if ln.strip()]
        rundir = os.path.join(ROOT, "benchmarks", "spec2017", f, "run")
        out.append((f, path, argv, rundir))
    return out


def sweep_runs():
    d = os.path.join(BIN, "pad")
    if not os.path.isdir(d):
        return []
    pads = sorted(int(f[len("spectre_v1_rv_pad"):]) for f in os.listdir(d)
                  if f.startswith("spectre_v1_rv_pad"))
    return [(f"pad{n}", os.path.join(d, f"spectre_v1_rv_pad{n}"), n) for n in pads]


# ----------------------------------------------------------------- running --
def run_gem5(outdir, core, defense, binary, argv=(), num_cpus=1, cwd=None,
             max_insts=0, timeout=None):
    os.makedirs(outdir, exist_ok=True)
    cmd = [GEM5, "-d", outdir, CONFIG, "--core", core, "--cmd", binary]
    cmd += DEFENSES[defense][0]
    if num_cpus > 1:
        cmd += ["--num-cpus", str(num_cpus)]
    if argv:
        cmd += ["--options", " ".join(argv)]
    if cwd:
        cmd += ["--cwd", cwd]
    if max_insts:
        cmd += ["--max-insts", str(max_insts)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT,
                           timeout=timeout)
        stdout = p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        stdout = (e.stdout or "") + (e.stderr or "") + "\nTIMEOUT\n"
    with open(os.path.join(outdir, "sim.out"), "w") as f:
        f.write(stdout)
    return stdout, parse_stats(os.path.join(outdir, "stats.txt"))


def parse_stats(path):
    """Pull the headline counters plus every spt.* counter."""
    want = {"simTicks": None, "numCycles": None, "committedInsts": None,
            "ipc": None, "l1dMissRate": None, "spt": {}}
    if not os.path.exists(path):
        return want
    with open(path) as f:
        for line in f:
            m = re.match(r"(\S+)\s+([\d.eE+-]+)", line)
            if not m:
                continue
            k, v = m.group(1), m.group(2)
            try:
                val = float(v)
            except ValueError:
                continue
            if k.endswith("simTicks"):
                want["simTicks"] = val
            elif k.endswith("numCycles") and want["numCycles"] is None:
                want["numCycles"] = val
            elif k.endswith("committedInsts") and want["committedInsts"] is None:
                want["committedInsts"] = val
            elif k.endswith(".ipc") and want["ipc"] is None:
                want["ipc"] = val
            elif "dcache" in k and k.endswith("overallMissRate::total"):
                if want["l1dMissRate"] is None:
                    want["l1dMissRate"] = val
            elif ".spt." in k:
                want["spt"][k.split(".spt.")[-1]] = val
    return want


def parse_poc(stdout):
    """Recovered string, accuracy, threshold, per-char best guesses."""
    out = {"expected": None, "recovered": None, "accuracy": None,
           "threshold": None, "hit_cyc": None, "miss_cyc": None, "per_char": []}
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
        out["accuracy"] = {"correct": a, "total": b, "frac": (a / b if b else 0.0)}
    for mm in re.finditer(r"best='(.)' \(0x([0-9a-f]+), hits=(\d+)\)", stdout):
        out["per_char"].append({"char": mm.group(1), "byte": int(mm.group(2), 16),
                                "hits": int(mm.group(3))})
    return out


# -------------------------------------------------------------- job build --
def build_jobs(args):
    jobs = []
    for core in args.cores:
        if args.suite == "poc":
            for name, stem, ncpu, is_poc in POCS:
                for d in args.defenses or POC_DEFENSES:
                    suffix = DEFENSES[d][1]
                    # The software barrier needs its own binary; skip the
                    # combination when that binary was not built.
                    binary = os.path.join(BIN, stem + suffix)
                    if not os.path.exists(binary):
                        continue
                    jobs.append(dict(kind="poc", core=core, defense=d,
                                     name=name, binary=binary, argv=[],
                                     num_cpus=ncpu, cwd=None, is_poc=is_poc,
                                     max_insts=0, timeout=args.timeout))
        elif args.suite == "spec":
            for name, path, argv, rundir in spec_workloads():
                for d in args.defenses or MAIN_DEFENSES:
                    if DEFENSES[d][1]:      # needs a recompiled binary
                        continue
                    jobs.append(dict(kind="spec", core=core, defense=d,
                                     name=name, binary=path, argv=argv,
                                     num_cpus=1, cwd=rundir, is_poc=False,
                                     max_insts=args.max_insts,
                                     timeout=args.timeout))
        elif args.suite == "sweep":
            for name, path, pad in sweep_runs():
                jobs.append(dict(kind="sweep", core=core, defense="baseline",
                                 name=name, binary=path, argv=[], num_cpus=1,
                                 cwd=None, is_poc=True, pad=pad,
                                 max_insts=0, timeout=args.timeout))
    if args.only:
        jobs = [j for j in jobs if any(o in j["name"] for o in args.only)]
    return jobs


def work(job):
    outdir = os.path.join(RESULTS, job["core"], job["defense"], job["name"])
    stdout, stats = run_gem5(outdir, job["core"], job["defense"], job["binary"],
                             job["argv"], job["num_cpus"], job["cwd"],
                             job["max_insts"], job["timeout"])
    rec = {"suite": job["kind"], "core": job["core"], "defense": job["defense"],
           "workload": job["name"], "binary": os.path.basename(job["binary"]),
           "num_cpus": job["num_cpus"], "stats": stats}
    if "pad" in job:
        rec["pad"] = job["pad"]
    m = re.search(r"Exited @ tick \d+: (.*)", stdout)
    rec["exit"] = m.group(1).strip() if m else "CRASH/NO-EXIT"

    if job["is_poc"]:
        rec["poc"] = parse_poc(stdout)
        acc = rec["poc"].get("accuracy")
        msg = (f"leaked {acc['correct']}/{acc['total']}" if acc
               else "NO ACCURACY LINE")
    elif job["kind"] == "spec":
        s = rec["stats"]
        msg = (f"ipc={s['ipc']:.3f} cycles={s['numCycles']:.0f}"
               if s["ipc"] else "NO STATS")
    else:
        rec["self_test"] = ("CHANNEL OK" in stdout)
        msg = f"channel {'OK' if rec['self_test'] else 'FAIL'}"

    print(f"[{job['core']:5s}] {job['defense']:9s} {job['name']:22s} -> "
          f"{msg}  [{rec['exit']}]", flush=True)
    return rec


def summarize(runs):
    """Security table: baseline must leak, every defense must not."""
    poc = [r for r in runs if r.get("poc") and r["poc"].get("accuracy")]
    if not poc:
        return
    print("\n=== Security summary (bytes recovered) ===")
    cores = sorted({r["core"] for r in poc})
    loads = sorted({r["workload"] for r in poc})
    defs_ = [d for d in POC_DEFENSES if any(r["defense"] == d for r in poc)]
    for core in cores:
        print(f"\n{core}:")
        print(f"  {'workload':24s} " + " ".join(f"{d:>10s}" for d in defs_))
        for w in loads:
            cells = []
            for d in defs_:
                hit = [r for r in poc if r["core"] == core and
                       r["workload"] == w and r["defense"] == d]
                if not hit:
                    cells.append(f"{'-':>10s}")
                else:
                    a = hit[0]["poc"]["accuracy"]
                    cells.append(f"{a['correct']:>6d}/{a['total']:<3d}")
            print(f"  {w:24s} " + " ".join(cells))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="poc", choices=["poc", "spec", "sweep"])
    ap.add_argument("--cores", nargs="+", default=["boom"],
                    choices=["boom", "p870"])
    ap.add_argument("--defenses", nargs="+", default=None,
                    choices=sorted(DEFENSES),
                    help="default: baseline/lfence/fence/spt (poc) or "
                         "baseline/fence/spt (spec)")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--only", nargs="+", default=None,
                    help="substring filter on workload names")
    ap.add_argument("--max-insts", type=int, default=200_000_000,
                    help="committed-instruction cap for the spec suite")
    ap.add_argument("--timeout", type=int, default=None,
                    help="per-run wall-clock limit in seconds")
    ap.add_argument("--dry-summary", action="store_true",
                    help="print results but do not update results.json")
    args = ap.parse_args()

    if not os.path.exists(GEM5):
        sys.exit(f"gem5 not found at {GEM5}; set $GEM5 or run `make gem5`")
    jobs = build_jobs(args)
    if not jobs:
        sys.exit(f"no runs for suite '{args.suite}'. "
                 f"Did you run `make benchmarks`?")
    print(f"{len(jobs)} runs, {args.jobs} at a time\n")

    with cf.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        new = list(ex.map(work, jobs))

    summarize(new)
    if args.dry_summary:
        return

    path = os.path.join(RESULTS, "results.json")
    results = {"gem5": GEM5, "runs": []}
    if os.path.exists(path):
        with open(path) as f:
            results["runs"] = json.load(f).get("runs", [])
    key = lambda r: (r["core"], r["defense"], r["workload"])
    fresh = {key(r) for r in new}
    results["runs"] = [r for r in results["runs"] if key(r) not in fresh] + new

    os.makedirs(RESULTS, exist_ok=True)
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
