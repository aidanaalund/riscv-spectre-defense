# RISC-V Spectre Defense Project

## Project Structure (TBD)

```
spectre-defenses-riscv-gem5/
├── README.md                          # Project overview, setup, and usage
├── .gitignore
│
├── docs/
│   ├── architecture.md                # System design and defense mechanisms
│   ├── spectre-background.md          # Spectre vulnerability explanation
│   ├── riscv-implementation.md        # RISC-V specific details
│   ├── building.md                    # Build instructions
│   └── results/                       # Research papers, experiment results
│       └── benchmarks.md
│
├── src/                               # gem5 extension code
│   ├── cpu/
│   │   ├── o3/
│   │   │   ├── spectre_defense.hh     # Defense mechanism headers
│   │   │   ├── spectre_defense.cc     # Defense implementations
│   │   │   ├── fetch.hh (modified)    # Patched fetch stage
│   │   │   └── execute.hh (modified)  # Patched execution stage
│   │   └── riscv/
│   │       ├── defs.hh (modified)     # RISC-V instruction definitions
│   │       └── faults.hh (modified)   # RISC-V fault handling
│   │
│   ├── mem/
│   │   ├── cache.hh (modified)        # Cache side-channel modifications
│   │   └── tlb.hh (modified)          # TLB defense modifications
│   │
│   └── arch/
│       └── riscv/
│           ├── isa.cc (modified)      # ISA-level defense hooks
│           └── spectre_csr.hh         # Custom CSRs for defenses
│
├── configs/                           # Simulation configuration scripts
│   ├── common/
│   │   ├── defaults.py                # Default parameters
│   │   ├── cpu_types.py               # CPU configuration options
│   │   └── memory.py                  # Memory hierarchy setup
│   │
│   ├── riscv/
│   │   ├── simple_system.py           # Basic single-core system
│   │   ├── o3_system.py               # O3 CPU system
│   │   └── multicore_system.py        # Multi-core configurations
│   │
│   └── defenses/
│       ├── baseline.py                # No defenses
│       ├── lfb_isolation.py           # Load-to-use Fence
│       ├── slh.py                     # Speculative Load Hardening
│       ├── csds.py                    # Cache-based defense
│       └── combined.py                # Multiple defenses
│
├── benchmarks/                        # Test programs
│   ├── spectre_poc/                   # Proof-of-concept exploits
│   │   ├── spectre_v1.c
│   │   ├── spectre_v1_5.c
│   │   └── spectre_v2.c
│   │
│   ├── standard/                      # SPEC or other benchmarks
│   │   └── Makefile
│   │
│   ├── custom/                        # Custom test kernels
│   │   ├── cache_covert_channel.c
│   │   ├── timing_test.c
│   │   └── branch_predictor_test.c
│   │
│   └── build_benchmarks.sh
│
├── scripts/                           # Automation and analysis
│   ├── run_experiment.py              # Main simulation runner
│   ├── batch_runner.py                # Multi-config batch execution
│   ├── parse_results.py               # Parse gem5 stats output
│   ├── plot_results.py                # Generate graphs
│   ├── compare_defenses.py            # Defense effectiveness analysis
│   └── setup_gem5.sh                  # gem5 dependency setup
│
├── results/                           # Simulation outputs
│   ├── baseline/
│   ├── with_lfb/
│   ├── with_slh/
│   └── stats_summary.json
│
├── patches/                           # gem5 patch files (optional)
│   ├── spectre_defense.patch
│   └── riscv_enhancements.patch
│
├── tests/                             # Unit and integration tests
│   ├── unit/
│   │   ├── test_spectre_defense.py
│   │   └── test_csr_handling.py
│   │
│   └── integration/
│       ├── test_full_sim.py
│       └── test_benchmark_runs.py
│
├── Makefile                           # Build shortcuts
├──  requirements.txt                   # Python dependencies
```
