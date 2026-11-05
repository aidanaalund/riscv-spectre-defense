#!/usr/bin/env python3
"""Plot the Spectre/lfence experiment results for the paper.

Reads results/results.json (from run_experiment.py) and emits, per core:
  - figN_hist_<core>.png : for the FIRST secret byte, the hit count of the
    correct symbol, baseline vs lfence (the headline "leak vs no-leak" figure)
  - a printed summary table of recovered strings + accuracy + cycle overhead.

Matplotlib only; no seaborn. Falls back to a text summary if matplotlib is
unavailable so the script is still useful on a bare sim box.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")


def load():
    with open(os.path.join(RESULTS, "results.json")) as f:
        return json.load(f)


def summary(data):
    print(f"{'core':6} {'workload':15} {'defense':9} "
          f"{'recovered':12} {'acc':8} {'numCycles':>12}")
    for r in data["runs"]:
        poc = r.get("poc", {})
        acc = poc.get("accuracy")
        acc_s = f"{acc['correct']}/{acc['total']}" if acc else "-"
        rec = (poc.get("recovered") or "-")[:12]
        cyc = r["stats"].get("numCycles")
        print(f"{r['core']:6} {r['workload']:15} {r['defense']:9} "
              f"{rec:12} {acc_s:8} {str(cyc):>12}")


def plot(data):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"(matplotlib unavailable: {e}; text summary only)")
        return

    cores = sorted({r["core"] for r in data["runs"]})
    for core in cores:
        # Headline comparison: the Tournament pair (baseline leaks fully,
        # spec.fence blocks). Fall back to any poc-bearing baseline/lfence pair.
        def pick(defense):
            cands = [r for r in data["runs"] if r["core"] == core
                     and r["defense"] == defense and r.get("poc")]
            tourn = [r for r in cands if r.get("bp") == "BiMode"]
            return (tourn or cands or [None])[0]
        base = pick("baseline")
        lf = pick("lfence")
        if not (base and lf and base.get("poc") and lf.get("poc")):
            continue
        bc = base["poc"]["per_char"]
        lc = lf["poc"]["per_char"]
        if not bc or not lc:
            continue
        n = min(len(bc), len(lc))
        import numpy as np
        x = np.arange(n)
        bvals = [bc[i]["hits"] for i in range(n)]
        lvals = [lc[i]["hits"] for i in range(n)]
        chars = [bc[i]["char"] for i in range(n)]
        w = 0.4
        fig, ax = plt.subplots(figsize=(6, 3.2))
        ax.bar(x - w/2, bvals, w, label=f"baseline ({base['bp']})", color="#c0392b")
        ax.bar(x + w/2, lvals, w, label=f"spec.fence ({lf['bp']})", color="#2980b9")
        ax.set_xticks(x)
        ax.set_xticklabels([f"{i}\n'{c}'" for i, c in enumerate(chars)])
        ax.set_xlabel("recovered byte position (baseline char shown)")
        ax.set_ylabel("hits on best symbol / REP")
        ax.set_title(f"Spectre v1: leak (baseline) vs blocked (spec.fence) — {core}")
        ax.legend()
        fig.tight_layout()
        out = os.path.join(RESULTS, f"fig_hist_{core}.png")
        fig.savefig(out, dpi=150)
        print(f"wrote {out}")


def plot_byte0_histogram(data):
    """Canonical Flush+Reload figure: byte-0 hit count per candidate symbol
    (0..255), baseline (sharp peak at the secret) vs spec.fence (flat)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return

    def load_hist(run):
        p = os.path.join(RESULTS, run["core"], run["workload"], "sim.out")
        h = [0] * 256
        if not os.path.exists(p):
            return None
        for line in open(p):
            if line.startswith("HIST "):
                _, sym, hits = line.split()
                h[int(sym)] = int(hits)
        return h

    cores = sorted({r["core"] for r in data["runs"]})
    for core in cores:
        def pick(defense):
            cs = [r for r in data["runs"] if r["core"] == core
                  and r["defense"] == defense and r.get("poc")]
            bi = [r for r in cs if r.get("bp") == "BiMode"]
            return (bi or cs or [None])[0]
        base, lf = pick("baseline"), pick("lfence")
        if not (base and lf):
            continue
        hb, hl = load_hist(base), load_hist(lf)
        if not hb or not any(hb):
            continue
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(8, 3), sharey=True)
        a1.bar(range(256), hb, color="#c0392b", width=1.0)
        a1.set_title(f"baseline ({base['bp']}): secret byte leaks")
        a1.set_xlabel("candidate symbol (byte value)")
        a1.set_ylabel("hits / REP")
        peak = hb.index(max(hb))
        a1.annotate(f"'{chr(peak)}' ({peak})", xy=(peak, max(hb)),
                    xytext=(peak + 30, max(hb) * 0.85),
                    arrowprops=dict(arrowstyle="->"))
        a2.bar(range(256), hl, color="#2980b9", width=1.0)
        a2.set_title(f"spec.fence ({lf['bp']}): no leak")
        a2.set_xlabel("candidate symbol (byte value)")
        fig.suptitle(f"Flush+Reload of secret byte 0 — {core}")
        fig.tight_layout()
        out = os.path.join(RESULTS, f"fig_byte0_{core}.png")
        fig.savefig(out, dpi=150)
        print(f"wrote {out}")


def plot_ltage(data):
    """The predictor-resistance figure: under the core's own default LTAGE,
    naive periodic mistraining leaks only byte 0, but randomized run-length +
    history-decorrelation mistraining recovers the whole secret -- and the
    spec.fence defense still blocks it. Grouped bars of best-symbol hits per
    byte position for the three LTAGE runs."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        return

    def by_name(name, core):
        for r in data["runs"]:
            if r["core"] == core and r["workload"] == name and r.get("poc"):
                return r
        return None

    series = [("spectre_base_ltage",        "periodic (naive)",        "#c0392b"),
              ("spectre_rand_ltage",         "randomized + decorrelate", "#e67e22"),
              ("spectre_rand_lfence_ltage",  "randomized + spec.fence",  "#2980b9")]
    for core in sorted({r["core"] for r in data["runs"]}):
        runs = [(by_name(n, core), lbl, col) for n, lbl, col in series]
        if not all(r for r, _, _ in runs):
            continue
        n = min(len(r["poc"]["per_char"]) for r, _, _ in runs)
        if n == 0:
            continue
        x = np.arange(n)
        w = 0.26
        fig, ax = plt.subplots(figsize=(7, 3.2))
        for k, (r, lbl, col) in enumerate(runs):
            pc = r["poc"]["per_char"]
            vals = [pc[i]["hits"] for i in range(n)]
            acc = r["poc"].get("accuracy") or {}
            tag = f"{acc.get('correct','?')}/{acc.get('total','?')}"
            ax.bar(x + (k - 1) * w, vals, w, label=f"{lbl}  [{tag}]", color=col)
        # expected secret chars from whichever run recovered them
        secret = next((r["poc"]["expected"] for r, _, _ in runs
                       if r["poc"].get("expected")), "")
        ax.set_xticks(x)
        ax.set_xticklabels([f"{i}\n'{secret[i]}'" if i < len(secret) else str(i)
                            for i in range(n)])
        ax.set_xlabel("secret byte position")
        ax.set_ylabel("hits on best symbol / REP")
        ax.set_title(f"Defeating LTAGE: adaptive mistraining vs defense — {core}")
        ax.legend(fontsize=8)
        fig.tight_layout()
        out = os.path.join(RESULTS, f"fig_ltage_{core}.png")
        fig.savefig(out, dpi=150)
        print(f"wrote {out}")


if __name__ == "__main__":
    if not os.path.exists(os.path.join(RESULTS, "results.json")):
        sys.exit("results/results.json not found; run scripts/run_experiment.py")
    d = load()
    summary(d)
    plot(d)
    plot_byte0_histogram(d)
    plot_ltage(d)
