/*
 * spectre-defense project: Speculative Privacy Tracking (SPT). See spt.hh.
 */

#include "cpu/o3/spt.hh"

#include <algorithm>
#include <limits>
#include <unordered_set>

#include "base/logging.hh"
#include "base/trace.hh"
#include "cpu/o3/cpu.hh"
#include "cpu/o3/dyn_inst.hh"
#include "debug/SPT.hh"

namespace gem5
{

namespace o3
{

namespace
{

SPT::Untaint
parseUntaint(const std::string &s)
{
    if (s == "none") return SPT::Untaint::None;
    if (s == "fwd") return SPT::Untaint::Fwd;
    if (s == "bwd") return SPT::Untaint::Bwd;
    if (s == "ideal") return SPT::Untaint::Ideal;
    fatal("sptUntaint must be none|fwd|bwd|ideal, got '%s'", s);
}

SPT::Mode
parseMode(const std::string &defense)
{
    if (defense == "none") return SPT::Mode::None;
    if (defense == "fence") return SPT::Mode::Fence;
    if (defense == "spt") return SPT::Mode::Spt;
    fatal("specDefense must be none|fence|spt, got '%s'", defense);
}

bool
parseFuturistic(const std::string &s)
{
    if (s == "spectre") return false;
    if (s == "futuristic") return true;
    fatal("sptThreatModel must be spectre|futuristic, got '%s'", s);
}

/**
 * Ops for which backward untaint is sound on RV64: the result is a bijective
 * function of either operand when the other is known. The 32-bit "*w" forms
 * are deliberately absent: they truncate their inputs to bits [31:0], so the
 * upper 32 bits of a source cannot be recovered from the result.
 */
const std::unordered_set<std::string> invertibleOps = {
    "add", "addi", "sub", "xor", "xori",
    "c_add", "c_addi", "c_sub", "c_xor", "c_mv",
    "c_addi16sp", "c_addi4spn",
};

} // anonymous namespace

SPT::SPT(CPU *_cpu, const BaseO3CPUParams &p, unsigned num_phys_regs)
    : cpu(_cpu),
      mode(parseMode(p.specDefense)),
      futuristic(parseFuturistic(p.sptThreatModel)),
      untaintMode(parseUntaint(p.sptUntaint)),
      untaintWidth(p.sptUntaintWidth),
      lazyImplicitFlow(p.sptLazyImplicitFlow),
      taint(num_phys_regs, 0),
      numPhysRegs(num_phys_regs),
      stats(_cpu)
{
    fatal_if(tracking() && untaintMode != Untaint::Ideal && untaintWidth == 0,
             "sptUntaintWidth must be > 0 (use sptUntaint=ideal for an "
             "unbounded untaint bandwidth)");
}

bool
SPT::tracked(PhysRegIdPtr reg) const
{
    return reg && !reg->is(InvalidRegClass) && !reg->is(MiscRegClass) &&
           reg->flatIndex() < numPhysRegs;
}

bool
SPT::isTainted(PhysRegIdPtr reg) const
{
    return tracked(reg) && taint[reg->flatIndex()];
}

void
SPT::setTaint(PhysRegIdPtr reg, bool t)
{
    if (tracked(reg))
        taint[reg->flatIndex()] = t;
}

bool
SPT::srcTainted(const DynInstPtr &inst, int idx) const
{
    return isTainted(inst->renamedSrcIdx(idx));
}

bool
SPT::argsTainted(const DynInstPtr &inst) const
{
    for (int i = 0; i < inst->numSrcRegs(); i++) {
        if (srcTainted(inst, i))
            return true;
    }
    return false;
}

bool
SPT::addrTainted(const DynInstPtr &inst) const
{
    // Every RV64 memory op (scalar, FP, RVC, LR/SC, AMO) carries its base
    // address register in source slot 0; slot 1, if any, is store data.
    return inst->isMemRef() && inst->numSrcRegs() > 0 && srcTainted(inst, 0);
}

void
SPT::taintRenamedDest(PhysRegIdPtr reg)
{
    if (!tracking() || !tracked(reg))
        return;
    taint[reg->flatIndex()] = 1;
    stats.taintedAtRename++;
}

bool
SPT::gateBlocks(const DynInstPtr &inst) const
{
    switch (mode) {
      case Mode::None:
        return false;
      case Mode::Fence:
        // Every transmitter waits for the visibility point.
        return inst->isMemRef() && !inst->specUnsquashable();
      case Mode::Spt:
        // Transmitters at the VP were declassified by tick(), so a tainted
        // address here always means "not yet unsquashable".
        return addrTainted(inst);
    }
    return false;
}

void
SPT::noteDelayed(const DynInstPtr &inst)
{
    if (inst->specDelayed())
        return;
    inst->specDelayed(true);
    inst->specDelayStart = uint64_t(cpu->curCycle());
    stats.delayedTransmitters++;
    DPRINTF(SPT, "[sn:%llu] PC %s held: tainted address\n",
            inst->seqNum, inst->pcState());
}

void
SPT::noteReleased(const DynInstPtr &inst)
{
    if (!inst->specDelayed())
        return;
    inst->specDelayed(false);
    stats.delayedCycles += uint64_t(cpu->curCycle()) - inst->specDelayStart;
    DPRINTF(SPT, "[sn:%llu] PC %s released after %llu cycles\n",
            inst->seqNum, inst->pcState(),
            uint64_t(cpu->curCycle()) - inst->specDelayStart);
}

bool
SPT::deferSquash(const DynInstPtr &inst)
{
    // Only SPT needs this: under Fence no load has acted on a secret, so a
    // mispredicting branch leaks nothing by squashing immediately.
    if (!tracking() || !lazyImplicitFlow)
        return false;
    if (inst->specUnsquashable() || !argsTainted(inst))
        return false;

    inst->specPendingSquash(true);
    pending[inst->threadNumber].push_back(inst);
    stats.deferredSquashes++;
    DPRINTF(SPT, "[sn:%llu] PC %s tainted mispredict: squash deferred\n",
            inst->seqNum, inst->pcState());
    return true;
}

std::vector<DynInstPtr>
SPT::takeRaisableSquashes(ThreadID tid)
{
    std::vector<DynInstPtr> out;
    auto &list = pending[tid];
    for (auto it = list.begin(); it != list.end(); ) {
        const DynInstPtr &inst = *it;
        if (inst->isSquashed()) {
            it = list.erase(it);
        } else if (inst->specUnsquashable()) {
            inst->specSquashRaised(true);
            stats.raisedSquashes++;
            DPRINTF(SPT, "[sn:%llu] PC %s reached VP: raising squash\n",
                    inst->seqNum, inst->pcState());
            out.push_back(inst);
            it = list.erase(it);
        } else {
            ++it;
        }
    }
    std::sort(out.begin(), out.end(),
              [](const DynInstPtr &a, const DynInstPtr &b) {
                  return a->seqNum < b->seqNum;
              });
    return out;
}

void
SPT::updateVisibility(ThreadID tid)
{
    // Walk the ROB oldest-first. An instruction is unsquashable once every
    // older control inst has resolved (Spectre) or every older inst has
    // completed (Futuristic). A branch with a deferred squash counts as
    // unresolved: readyToCommit() is false while the squash is pending.
    bool prev_ok = true;
    for (const DynInstPtr &inst : cpu->rob.getInstList(tid)) {
        if (inst->isSquashed())
            continue;

        inst->specUnsquashable(prev_ok);

        const bool complete = inst->readyToCommit() && inst->isExecuted() &&
                              inst->getFault() == NoFault;
        if (futuristic) {
            if (!complete)
                prev_ok = false;
        } else if (inst->isControl() && !complete) {
            prev_ok = false;
        }

        // Declassify: a transmitter at the VP is about to leak its address
        // non-speculatively, so its address operand is now public.
        if (tracking() && inst->specUnsquashable() && addrTainted(inst)) {
            setTaint(inst->renamedSrcIdx(0), false);
            stats.vpUntaints++;
            DPRINTF(SPT, "[sn:%llu] PC %s at VP: address declassified\n",
                    inst->seqNum, inst->pcState());
        }
    }
}

bool
SPT::backwardInvertible(const DynInstPtr &inst) const
{
    return invertibleOps.count(inst->staticInst->getName()) != 0;
}

void
SPT::propagateUntaint(ThreadID tid)
{
    if (untaintMode == Untaint::None)
        return;

    const bool ideal = untaintMode == Untaint::Ideal;
    const bool bwd = untaintMode == Untaint::Bwd || ideal;
    const size_t budget = ideal ? std::numeric_limits<size_t>::max()
                                : untaintWidth;

    struct Item { PhysRegIdPtr reg; bool backward; };
    std::vector<Item> queue;

    auto enqueue = [&](PhysRegIdPtr reg, bool backward) {
        for (const Item &q : queue) {
            if (q.reg == reg)
                return true;
        }
        if (queue.size() >= budget)
            return false;
        queue.push_back({reg, backward});
        return true;
    };

    do {
        queue.clear();
        bool full = false;

        // Oldest instructions first; within an instruction, destinations
        // (forward) before sources (backward), as in the original code.
        for (const DynInstPtr &inst : cpu->rob.getInstList(tid)) {
            if (inst->isSquashed())
                continue;

            // Forward: a non-memory instruction whose operands are all
            // public produces a public result. Load results stay secret.
            if (!inst->isMemRef() && !argsTainted(inst)) {
                for (int i = 0; i < inst->numDestRegs(); i++) {
                    PhysRegIdPtr d = inst->renamedDestIdx(i);
                    if (isTainted(d) && !enqueue(d, false))
                        full = true;
                }
            }

            // Backward: invertible op with a public result and exactly one
            // secret operand -> that operand is public too.
            if (bwd && inst->numDestRegs() == 1 && backwardInvertible(inst)) {
                PhysRegIdPtr d = inst->renamedDestIdx(0);
                if (tracked(d) && !isTainted(d)) {
                    int tainted_src = -1, n_tainted = 0;
                    for (int i = 0; i < inst->numSrcRegs(); i++) {
                        if (srcTainted(inst, i)) {
                            tainted_src = i;
                            n_tainted++;
                        }
                    }
                    if (n_tainted == 1 &&
                        !enqueue(inst->renamedSrcIdx(tainted_src), true)) {
                        full = true;
                    }
                }
            }
        }

        if (full)
            stats.untaintQueueFull++;

        for (const Item &q : queue) {
            if (!isTainted(q.reg))
                continue;
            setTaint(q.reg, false);
            if (q.backward)
                stats.bwdUntaints++;
            else
                stats.fwdUntaints++;
        }
    } while (ideal && !queue.empty());
}

void
SPT::tick()
{
    if (mode == Mode::None)
        return;
    for (ThreadID tid : cpu->activeThreads) {
        updateVisibility(tid);
        if (tracking())
            propagateUntaint(tid);
    }
}

SPT::SPTStats::SPTStats(CPU *cpu)
    : statistics::Group(cpu, "spt"),
      ADD_STAT(taintedAtRename, statistics::units::Count::get(),
               "Destination registers tainted at rename"),
      ADD_STAT(vpUntaints, statistics::units::Count::get(),
               "Transmitter address registers declassified at the VP"),
      ADD_STAT(fwdUntaints, statistics::units::Count::get(),
               "Registers untainted by forward propagation"),
      ADD_STAT(bwdUntaints, statistics::units::Count::get(),
               "Registers untainted by backward propagation"),
      ADD_STAT(delayedTransmitters, statistics::units::Count::get(),
               "Loads/stores held back because of a tainted address"),
      ADD_STAT(delayedCycles, statistics::units::Cycle::get(),
               "Total cycles transmitters were held back"),
      ADD_STAT(deferredSquashes, statistics::units::Count::get(),
               "Tainted branch mispredicts whose squash was deferred"),
      ADD_STAT(raisedSquashes, statistics::units::Count::get(),
               "Deferred squashes raised once the branch reached the VP"),
      ADD_STAT(untaintQueueFull, statistics::units::Count::get(),
               "Cycles in which untaint candidates exceeded the bandwidth")
{
}

} // namespace o3
} // namespace gem5
