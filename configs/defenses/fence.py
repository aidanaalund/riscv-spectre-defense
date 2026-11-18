"""Hardware speculation fence: delay every memory access to the visibility point.

This models "lfence after every conditional branch" WITHOUT recompiling the
workload: a load or store is not sent to the TLB/caches until no older branch
is unresolved. It is the conservative upper bound on delay-based defenses and
the natural performance comparison point for our software `spec.fence`, which
cannot be applied to SPEC without a compiler pass.

Equivalent to the SPT mechanism with every value permanently secret, so it
delays exactly the same instruction set as --defense spt and only the release
condition differs. That is also how the two source papers obtain their fence
baselines: SPT's `--scheme=SpectreSafeFence` and the delay-on-miss paper's
"eager delay" (Sakalis et al., ISCA'19, Section 3.2).
"""


def apply(system, cpus, args):
    for cpu in cpus:
        cpu.specDefense = "fence"
