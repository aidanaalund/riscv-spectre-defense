"""Baseline core parameters for the RV64GC O3 model.

Loosely modeled on a BOOM "LargeBoom"-class core, cross-checked against
SoomRV (4-wide, 64-entry ROB) and RSD. Values are NOT cycle-accurate copies;
they are chosen so the speculation window (ROB/LSQ depth, branch resolution
latency) is realistic for the cores this project cites. Change them here only,
and record why, so every defense is compared against the same baseline.
"""

CLOCK = "1GHz"

CORE = dict(
    # Pipeline widths (LargeBoom: 3-wide decode/dispatch)
    fetchWidth=3,
    decodeWidth=3,
    renameWidth=3,
    dispatchWidth=3,
    issueWidth=4,       # BOOM Large: 4 issue ports (int/mem/fp mix)
    wbWidth=4,
    commitWidth=3,
    squashWidth=3,
    # Window sizes (LargeBoom: ROB 96, LDQ/STQ 24, 100 int / 96 fp phys regs)
    numROBEntries=96,
    numIQEntries=64,
    LQEntries=24,
    SQEntries=24,
    numPhysIntRegs=100,
    numPhysFloatRegs=96,
    numPhysVecRegs=64,
    numPhysVecPredRegs=32,
    numPhysCCRegs=0,
    # Front-end / misprediction penalty roughly BOOM's ~10 cycles
    fetchToDecodeDelay=1,
    decodeToRenameDelay=1,
    renameToIEWDelay=1,
    iewToCommitDelay=1,
    commitToFetchDelay=1,
    # Caches (LargeBoom: 32KiB 8-way L1s, inclusive L2)
)

CACHE = dict(
    l1i=dict(size="32KiB", assoc=8, tag_latency=1, data_latency=1, response_latency=1,
             mshrs=4, tgts_per_mshr=8),
    l1d=dict(size="32KiB", assoc=8, tag_latency=1, data_latency=2, response_latency=1,
             mshrs=8, tgts_per_mshr=8),
    l2=dict(size="512KiB", assoc=8, tag_latency=6, data_latency=6, response_latency=2,
            mshrs=16, tgts_per_mshr=12),
)

MEM_SIZE = "512MiB"
MEM_LATENCY = "50ns"   # SimpleMemory fixed latency; gives a clear hit/miss gap
BRANCH_PRED = "LTAGE"  # BOOM uses TAGE; needed so v1 mistraining behaves realistically
