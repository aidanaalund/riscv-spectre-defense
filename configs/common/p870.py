"""SiFive P870-like core parameters for the RV64GC O3 model.

Sources: Chips and Cheese, "Hot Chips 2023: SiFive's P870 Takes RISC-V
Further", and the Hot Chips 2023 slides (ROB size). Entries tagged ASSUMED are
not published; they are placeholders to be swept, not facts. Keep the tags
current so results can say which parameters are cited and which are guesses.

gem5 O3 has a unified issue queue and no non-scheduling dispatch queues, so
per-port schedulers are approximated by one numIQEntries pool.
"""

CLOCK = "3GHz"          # "well into the 3 GHz range" (article Q&A)

CORE = dict(
    # 6-wide fetch/decode/rename (article)
    fetchWidth=6,
    decodeWidth=6,
    renameWidth=6,
    dispatchWidth=6,
    issueWidth=8,       # 6 int ports + 2 FP pipes
    wbWidth=8,
    commitWidth=6,      # ASSUMED = rename width
    squashWidth=6,
    # Window sizes
    numROBEntries=1120,  # Hot Chips slides: "up to 1120 instructions"
    numIQEntries=192,    # ASSUMED (6 int queues + FP; depths not published)
    LQEntries=96,        # ASSUMED ("a bit light" vs. ROB; sizes not published)
    SQEntries=64,        # ASSUMED
    # ASSUMED: phys regs, not published. With a 1120-entry ROB these, not the
    # ROB, bound the real in-flight window; sweep them with the ROB.
    numPhysIntRegs=512,
    numPhysFloatRegs=384,
    numPhysVecRegs=256,
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
    # 64 KB I-cache (article). Associativity ASSUMED.
    l1i=dict(size="64KiB", assoc=4, tag_latency=1, data_latency=1, response_latency=1,
             mshrs=8, tgts_per_mshr=8),
    # L1D size/assoc not published: ASSUMED 64 KB 8-way. 4-cycle load-to-use
    # (article), approximated as tag 1 + data 3.
    l1d=dict(size="64KiB", assoc=8, tag_latency=1, data_latency=3, response_latency=1,
             mshrs=16, tgts_per_mshr=8),
    # Shared L2: 4 MB example, 16-cycle latency (article). Assoc ASSUMED.
    l2=dict(size="4MiB", assoc=16, tag_latency=8, data_latency=8, response_latency=2,
            mshrs=32, tgts_per_mshr=12),
)

MEM_SIZE = "512MiB"
MEM_LATENCY = "50ns"
# Article: 8-table TAGE (16K entries), 64-entry RAS, 2.5K-entry indirect pred.
# gem5's LTAGE is the closest stock predictor; its sizes are set in the config.
BRANCH_PRED = "LTAGE"
RAS_SIZE = 64
