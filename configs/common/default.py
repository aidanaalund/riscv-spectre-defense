"""
Baseline core parameters for the RV64GC O3 model.

Loosely modeled on a BOOM "LargeBoom"-class core (SonicBOOM, riscv-boom
v3 config-mixins.scala, WithNLargeBooms). Parameters tagged ASSUMED are not
taken from BOOM's published config (latencies, L2, clock, memory).
Values are NOT cycle-accurate copies; they are chosen so the speculation window 
(ROB/LSQ depth, branch resolution latency) is realistic for the cores this project cites. 
Every defense is compared against the same baseline set here.

Sources:
 - https://github.com/riscv-boom/riscv-boom
 - https://boom-core.org/
 - https://people.eecs.berkeley.edu/~krste/papers/SonicBOOM-CARRV2020.pdf
 - https://carrv.github.io/2020/slides/CARRV2020_slides_15_Zhao.pdf
"""

CLOCK = "1GHz" # This clock was used when authors synthesized on commercial FinFET process (Zhao slides)

CORE = dict(
    # Pipeline widths (LargeBoom: 3-wide decode/dispatch)
    fetchWidth=8, # LargeBoom fetchWidth=8 (decode is 3)
    decodeWidth=3,
    renameWidth=3,
    dispatchWidth=3,
    issueWidth=5, # BOOM Large: 3 INT + 1 MEM + 1 FP issue
    wbWidth=5,
    commitWidth=3,
    squashWidth=3,
    # Window sizes (LargeBoom: ROB 96, LDQ/STQ 24, 100 int / 96 fp phys regs)
    numROBEntries=96,
    numIQEntries=72, # MEM 16 + INT 32 + FP 24 (separate queues in BOOM)
    LQEntries=24,
    SQEntries=24,
    numPhysIntRegs=100,
    numPhysFloatRegs=96,
    # BOOM has no vector unit; these are unused filler required by gem5
    numPhysVecRegs=64,
    numPhysVecPredRegs=32,
    numPhysCCRegs=0,
    # Front-end / misprediction penalty roughly BOOM's ~10 cycles (ASSUMED,
    # unsourced; stage delays are tuning knobs, measure the real penalty)
    fetchToDecodeDelay=1,
    decodeToRenameDelay=1,
    renameToIEWDelay=1,
    iewToCommitDelay=1,
    commitToFetchDelay=1,
    # Caches: Size and associativity taken from paper. Latencies/MSHR targets ASSUMED.
)

CACHE = dict(
    l1i=dict(size="32KiB", assoc=8, tag_latency=1, data_latency=1, response_latency=1,
             mshrs=4, tgts_per_mshr=8),
    l1d=dict(size="32KiB", assoc=8, tag_latency=1, data_latency=2, response_latency=1,
             mshrs=4, tgts_per_mshr=8),   # LargeBoom: 4 D-cache MSHRs
    l2=dict(size="512KiB", assoc=8, tag_latency=6, data_latency=6, response_latency=2,
            mshrs=16, tgts_per_mshr=12),
)

MEM_SIZE = "512MiB"
MEM_LATENCY = "50ns" # ASSUMED; SimpleMemory fixed latency; gives a clear hit/miss gap
BRANCH_PRED = "LTAGE" # BOOM uses TAGE
