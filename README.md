# RISC-V Spectre Defense Project

## Authors: Aidan Aalund, Logan Bristol, Andres Wearden

## Description

This repository contains source code for our course project for **ECE 382N-Sec: Security at the HW/SW Interface** (taught by Dr. Neil Zhao). The project aims to review defenses to Spectre-class vulnerabilities for common research and commercial RISC-V microprocessors. SonicBOOM (Zhao et al.) and the SiFive P870 (SiFive, Inc.) were selected as representative examples. Within the gem5 microarchitectural simulator, two configurations for `o3cpu` are created to model the processors from publicly available documentation. We implement RISC-V versions of x86-64 Spectre defenses such as the `lfence` instruction, [speculative privacy tracking](https://github.com/FPSG-UIUC/SPT) (SPT) (Choudhary et al.), and [Delay on Miss + Value Prediction](https://dl.acm.org/doi/10.1145/3307650.3322216) (Sakalis et al.). Benchmarks will validate functionality and performance in application-level scenarios.

## How to use

Everything runs inside the project's Docker image (the host GCC miscompiles
gem5's O3 model — see `docker/README.md`). `make help` lists every target.

```sh
make docker-build     # once: build the toolchain image
make gem5             # build gem5 into gem5/build (incremental)
make benchmarks       # cross-compile the PoCs (+ SPEC CPU2017, if present)

make poc              # security:    every defense vs. the Spectre PoCs
make perf             # performance: every defense x core on SPEC CPU2017
make plot             # figures + tables into results/
```

Useful overrides: `JOBS=4`, `CORES="boom p870"`, `MAX_INSTS=200000000`,
`DOCKER=0` (run directly, e.g. when you are already inside the container).

## Defenses

| `--defense` | Kind | What it does |
|---|---|---|
| `baseline` | — | Undefended core. |
| `lfence` | software | Our custom-0 `spec.fence` barrier placed after the bounds check. Needs a recompiled binary, so it is used for the PoCs only. |
| `fence` | hardware | Delays **every** load/store until no older branch is unresolved. Models "lfence after every branch" on unmodified binaries, so it is the fence data point for SPEC. |
| `spt` | hardware | Speculative Privacy Tracking: delays only accesses whose **address depends on a secret**, and declassifies values as they become safe. |

`spt` accepts the original artifact's knobs: `--spt-untaint
{none,fwd,bwd,ideal}`, `--spt-threat-model {spectre,futuristic}`,
`--spt-untaint-width N`, `--spt-no-implicit`. See
`docs/spectre-defense-port-plan.md` for the port's design and what is still
outstanding (Delay-on-Miss + Value Prediction).

### Benchmarks

The Spectre PoCs live in `benchmarks/spectre_poc/` and are built by
`make benchmarks`. SPEC CPU2017 is licensed software and is **not** in this
repo: drop each benchmark's sources and test inputs into
`benchmarks/spec2017/<name>/{src,run}/` as described in
`benchmarks/spec2017/MANIFEST.json`, then re-run `make benchmarks`.
