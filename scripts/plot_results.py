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
        def pick(defense):
            cands = [r for r in data["runs"] if r["core"] == core
                     and r["defense"] == defense and r.get("poc")
                     and "pad" not in r]
            return (cands or [None])[0]
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

    def by_name(core, name):
        for r in data["runs"]:
            if r["core"] == core and r["workload"] == name and r.get("poc"):
                return r
        return None

    # One row per training schedule (both under LTAGE); columns baseline |
    # spec.fence. Both schedules leak byte 0; spec.fence flattens every row.
    rows = [("LTAGE, periodic training",        "spectre_base_ltage",  "spectre_lfence_ltage"),
            ("LTAGE, randomized + decorrelate", "spectre_rand_ltage",  "spectre_rand_lfence_ltage")]
    BASE_C, FENCE_C = "#eb6834", "#2a78d6"    # categorical slots 2 / 1
    INK, MUTED = "#0b0b0b", "#52514e"

    cores = sorted({r["core"] for r in data["runs"]})
    for core in cores:
        avail = [(lbl, by_name(core, b), by_name(core, f)) for lbl, b, f in rows]
        avail = [(lbl, b, f) for lbl, b, f in avail if b and f]
        hists = [(lbl, b, f, load_hist(b), load_hist(f)) for lbl, b, f in avail]
        hists = [h for h in hists if h[3] and h[4] and any(h[3])]
        if not hists:
            continue
        ymax = max(max(hb + hl) for _, _, _, hb, hl in hists) * 1.25
        fig, axes = plt.subplots(len(hists), 2, figsize=(8.5, 2.3 * len(hists) + 0.6),
                                 sharex=True, sharey=True, squeeze=False)
        secret0 = None
        for k, (lbl, b, f, hb, hl) in enumerate(hists):
            secret0 = secret0 or (b["poc"].get("expected") or " ")[0]
            for j, (h, run, col, tag) in enumerate(
                    [(hb, b, BASE_C, "baseline"), (hl, f, FENCE_C, "spec.fence")]):
                ax = axes[k][j]
                ax.bar(range(256), h, color=col, width=1.0)
                ax.set_ylim(0, ymax)
                ax.set_xlim(-2, 258)
                for s in ("top", "right"):
                    ax.spines[s].set_visible(False)
                ax.tick_params(colors=MUTED, labelsize=8)
                peak = h.index(max(h))
                if max(h) > 0 and run["defense"] == "baseline":
                    ax.annotate(f"'{chr(peak)}' (0x{peak:02x}) = {max(h)}/16",
                                xy=(peak, max(h)), xytext=(peak + 25, max(h) * 0.95),
                                fontsize=8, color=INK,
                                arrowprops=dict(arrowstyle="->", color=MUTED))
                else:
                    ax.text(128, ymax * 0.55, "no leak (flat)", ha="center",
                            fontsize=8, color=MUTED)
                acc = (run["poc"].get("accuracy") or {})
                ax.set_title(f"{tag} — {lbl}  [{acc.get('correct','?')}/"
                             f"{acc.get('total','?')} bytes]", fontsize=9, color=INK)
                if j == 0:
                    ax.set_ylabel("hits / REP", fontsize=8, color=MUTED)
                if k == len(hists) - 1:
                    ax.set_xlabel("candidate symbol (byte value)", fontsize=8, color=MUTED)
        fig.suptitle(f"Flush+Reload of secret byte 0 ('{secret0}') — {core}", color=INK)
        fig.tight_layout()
        out = os.path.join(RESULTS, f"fig_byte0_{core}.png")
        fig.savefig(out, dpi=150)
        plt.close(fig)
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
        ax.set_title(f"Mistraining vs Defense")
        ax.legend(fontsize=8)
        fig.tight_layout()
        out = os.path.join(RESULTS, f"fig_ltage_{core}.png")
        fig.savefig(out, dpi=150)
        print(f"wrote {out}")


def plot_window(data):
    """BOOM vs P870 speculation window: bytes recovered by the baseline PoC as
    N independent nops are inserted between the bounds check and the gadget
    load (LTAGE). The leak survives exactly while the padded gadget still fits
    in the core's ROB, so the cutoff lands just under each core's ROB size."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return
    sys.path.insert(0, os.path.join(ROOT, "configs"))
    try:
        from common import default as boom_cfg, p870 as p870_cfg
        rob = {"boom": boom_cfg.CORE["numROBEntries"],
               "p870": p870_cfg.CORE["numROBEntries"]}
    except Exception:
        rob = {"boom": 96, "p870": 1120}

    INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3de"
    style = {"boom": ("BOOM (LargeBoom-like)", "#2a78d6", "o"),
             "p870": ("SiFive P870-like",      "#eb6834", "s")}
    series = {}
    for r in data["runs"]:
        if "pad" in r and r.get("poc") and r["poc"].get("accuracy"):
            series.setdefault(r["core"], []).append(
                (r["pad"], r["poc"]["accuracy"]["correct"]))
    if not series:
        return

    cores = [c for c in ("boom", "p870") if c in series]
    fig, axes = plt.subplots(len(cores), 1, figsize=(7.5, 1.9 * len(cores) + 0.8),
                             sharex=True, squeeze=False)
    ticks = [0, 16, 32, 64, 128, 256, 512, 1024]
    for ax, core in zip(axes[:, 0], cores):
        pts = sorted(series[core])
        xs, ys = [p for p, _ in pts], [a for _, a in pts]
        lbl, col, mk = style[core]
        ax.step(xs, ys, where="post", color=col, lw=2, zorder=3)
        ax.plot(xs, ys, mk, color=col, ms=5, mec="white", mew=1, zorder=4)
        last_leak = max((p for p, a in pts if a > 0), default=None)
        first_block = min((p for p, a in pts if a == 0 and
                           (last_leak is None or p > last_leak)), default=None)
        ax.axvline(rob[core], color=MUTED, lw=1, ls="--", zorder=2)
        ax.text(rob[core] * 1.03, 4, f"ROB = {rob[core]}", fontsize=8,
                color=MUTED, va="center")
        if last_leak is not None and first_block is not None:
            ax.text(0.01, 0.5, f"leaks with ≤ {last_leak} nops\n"
                    f"blocked at ≥ {first_block} nops", transform=ax.transAxes,
                    fontsize=8, color=INK, va="center")
        ax.set_title(f"{lbl} (ROB {rob[core]})", fontsize=9, color=INK, loc="left")
        ax.set_xscale("symlog", base=2, linthresh=16)
        ax.set_xticks(ticks)
        ax.set_xticklabels([str(t) for t in ticks])
        ax.set_xlim(-1, 1500)
        ax.set_ylim(-0.6, 9)
        ax.set_yticks([0, 4, 8])
        ax.set_ylabel("bytes leaked\n(of 8)", fontsize=8, color=MUTED)
        ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.tick_params(colors=MUTED, labelsize=8)
    axes[-1, 0].set_xlabel("independent nops between bounds check and gadget load",
                           fontsize=9, color=MUTED)
    fig.suptitle("Spectre v1 speculation window: BOOM vs P870 (LTAGE, no defense)",
                 fontsize=10, color=INK)
    fig.tight_layout()
    out = os.path.join(RESULTS, "fig_window_boom_vs_p870.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


if __name__ == "__main__":
    if not os.path.exists(os.path.join(RESULTS, "results.json")):
        sys.exit("results/results.json not found; run scripts/run_experiment.py")
    d = load()
    summary(d)
    plot(d)
    plot_byte0_histogram(d)
    plot_ltage(d)
    plot_window(d)
