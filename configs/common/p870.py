"""
SiFive P870-like core parameters for the RV64GC O3 model.

Sources: Chips and Cheese, "Hot Chips 2023: SiFive's P870 Takes RISC-V
Further", and the Hot Chips 2023 P870 slides (ROB, rename regs, issue queues,
LQ/SQ). Vector issue queue/pipes are excluded (RV64GC workloads). Entries tagged ASSUMED are
not published; they are placeholders to be swept, not facts. Keep the tags
current so results can say which parameters are cited and which are guesses.

gem5 O3 has a unified issue queue and no non-scheduling dispatch queues, so
per-port schedulers are approximated by one numIQEntries pool.

Sources:
 - https://chipsandcheese.com/p/hot-chips-2023-sifives-p870-takes-risc-v-further
 - https://www.cnx-software.com/2023/08/30/sifive-unveils-p870-high-performance-core-discusses-future-of-risc-v/
 - https://hc2023.hotchips.org/assets/program/conference/day1/CPU2/P870%20for%20Hot%20Chips%20-%20FInal.pdf
 
"""

CLOCK = "3GHz"          # "well into the 3 GHz range" (article Q&A)

CORE = dict(
    # 6-wide decode/dispatch (slides). Fetch is 36 B/cycle (~9 4-byte insts).
    fetchWidth=9,       # derived from 36 B fetch; ASSUMED 4 B/inst # TODO: best guess
    decodeWidth=6,
    renameWidth=6, # TODO: best guess
    dispatchWidth=6,
    issueWidth=8,       # 6 int ports + 2 FP pipes (rough estimate)
    wbWidth=8,
    commitWidth=6,      # ASSUMED = rename width
    squashWidth=6,
    # Window sizes
    numROBEntries=1120,  # Hot Chips slides: "up to 1120 instructions"
    numIQEntries=176,    # slides: int 96 + FP 48 + LdSt 32 (vector 32 excluded)
    LQEntries=48,        # slides: 48 load buffer
    SQEntries=48,        # slides: 48 store buffers
    # Slides: "register renames" 228 int / 240 FP / 128 vec. Unclear whether
    # this counts total physical regs or rename regs beyond architectural; taken
    # as total. These, not the ROB, bound the real in-flight window.
    numPhysIntRegs=228,
    numPhysFloatRegs=240,
    numPhysVecRegs=128,
    numPhysVecPredRegs=32,
    numPhysCCRegs=0,
    # ~8-cycle mispredict penalty (article pipeline diagram): fetch->commit
    # redirect spread over the stage delays below.
    fetchToDecodeDelay=2,
    decodeToRenameDelay=1,
    renameToIEWDelay=2,
    iewToCommitDelay=1,
    commitToFetchDelay=2,
)

CACHE = dict(
    # 64 KB I-cache (slides). Associativity ASSUMED.
    l1i=dict(size="64KiB", assoc=4, tag_latency=1, data_latency=1, response_latency=1,
             mshrs=8, tgts_per_mshr=8),
    # 64 KB L1D (slides); associativity ASSUMED 8-way. 4-cycle load-to-use
    # (article), approximated as tag 1 + data 3.
    l1d=dict(size="64KiB", assoc=8, tag_latency=1, data_latency=3, response_latency=1,
             mshrs=16, tgts_per_mshr=8),
    # Shared L2: 4 MB example, 16-cycle latency (article). Assoc ASSUMED.
    l2=dict(size="4MiB", assoc=16, tag_latency=8, data_latency=8, response_latency=2,
            mshrs=32, tgts_per_mshr=12),
    # Not modeled: 16 MB L3
)

MEM_SIZE = "512MiB"
MEM_LATENCY = "50ns"
# Slides: 16K-entry TAGE, 64-entry RAS, 2.5K-entry indirect pred, 1K-entry
# next-line predictor (article: 8 tables, estimated).
# gem5's LTAGE is the closest stock predictor
BRANCH_PRED = "LTAGE"
RAS_SIZE = 64
