"""Speculative Privacy Tracking (Choudhary et al., MICRO'21), in hardware.

Implemented in gem5/src/cpu/o3/spt.{hh,cc}; see docs/spectre-defense-port-plan.md.
The flags below mirror the original artifact's run_spt.py so configurations map
onto the paper's:

  paper config          flags
  SecureBaseline        --spt-untaint none
  Fwd, NoShadowL1       --spt-untaint fwd
  Bwd, NoShadowL1       --spt-untaint bwd        (default)
  Ideal                 --spt-untaint ideal
(ShadowL1 / ShadowMem are not implemented yet.)
"""


def add_args(ap):
    g = ap.add_argument_group("SPT (--defense spt)")
    g.add_argument("--spt-threat-model", default="spectre",
                   choices=["spectre", "futuristic"])
    g.add_argument("--spt-untaint", default="bwd",
                   choices=["none", "fwd", "bwd", "ideal"])
    g.add_argument("--spt-untaint-width", type=int, default=3,
                   help="untaint broadcasts per cycle (original artifact: 3)")
    g.add_argument("--spt-no-implicit", action="store_true",
                   help="disable Lazy deferral of tainted branch squashes")


def apply(system, cpus, args):
    for cpu in cpus:
        cpu.specDefense = "spt"
        cpu.sptThreatModel = args.spt_threat_model
        cpu.sptUntaint = args.spt_untaint
        cpu.sptUntaintWidth = args.spt_untaint_width
        cpu.sptLazyImplicitFlow = not args.spt_no_implicit
