/*
 * spectre-defense project: Speculative Privacy Tracking (SPT) for the O3 CPU.
 *
 * A RISC-V / gem5-25.1 re-implementation of the defense from
 *   R. Choudhary, J. Yu, C. Fletcher, A. Morrison, "Speculative Privacy
 *   Tracking (SPT): Leaking Information From Speculative Execution Without
 *   Compromising Privacy", MICRO 2021.
 * ported from the authors' gem5 fork (github.com/FPSG-UIUC/SPT, itself built
 * on STT/InvisiSpec). See docs/spectre-defense-port-plan.md for what was kept,
 * what was dropped, and why.
 *
 * Model (matches the original code):
 *  - Every physical register written by an instruction is TAINTED (secret) at
 *    rename. Initial architectural state is public.
 *  - An instruction is UNSQUASHABLE (has reached the visibility point, VP)
 *    once every older control instruction has resolved (Spectre threat
 *    model) or every older instruction has completed (Futuristic model).
 *  - Loads, stores and AMOs are transmitters. A transmitter whose address
 *    operand is tainted is held back (not sent to the TLB/cache) until it
 *    reaches the VP. At the VP its address operand is DECLASSIFIED: the
 *    address is about to be leaked non-speculatively anyway.
 *  - Untaint propagation: forward (an ALU result computed only from public
 *    operands is public) and backward (for invertible ops, a public result
 *    and all-but-one public operands make the last operand public). Load
 *    results are never untainted by propagation (no shadow memory yet).
 *  - Implicit flow ("Lazy"): a mispredicted branch with tainted operands that
 *    is not yet unsquashable defers its squash until it is.
 *
 * RISC-V notes: x0 (decoded as an invalid RegId) and CSR/misc registers are
 * always public. The address of every RISC-V memory op is source operand 0.
 */

#ifndef __CPU_O3_SPT_HH__
#define __CPU_O3_SPT_HH__

#include <cstdint>
#include <list>
#include <string>
#include <vector>

#include "base/statistics.hh"
#include "cpu/o3/dyn_inst_ptr.hh"
#include "cpu/o3/limits.hh"
#include "cpu/reg_class.hh"
#include "params/BaseO3CPU.hh"

namespace gem5
{

namespace o3
{

class CPU;

class SPT
{
  public:
    /**
     * None  - no defense.
     * Fence - delay EVERY transmitter until it reaches the VP. Models an
     *         lfence after every branch without recompiling the workload,
     *         which is how both SPT (--scheme=SpectreSafeFence) and the
     *         delay-on-miss paper ("eager delay") get a software-fence
     *         baseline on unmodified binaries. Equivalent to SPT with
     *         everything permanently tainted, so it delays the same
     *         instruction set as Spt and only the condition differs.
     * Spt   - delay only transmitters whose address is secret.
     */
    enum class Mode { None, Fence, Spt };
    enum class Untaint { None, Fwd, Bwd, Ideal };

    SPT(CPU *_cpu, const BaseO3CPUParams &p, unsigned num_phys_regs);

    /** Is any delay-based defense active on this core? */
    bool enabled() const { return mode != Mode::None; }
    /** Is taint tracking live (SPT proper)? */
    bool tracking() const { return mode == Mode::Spt; }

    /** Taint queries. Untracked registers (x0, CSRs) are public. */
    bool isTainted(PhysRegIdPtr reg) const;
    bool srcTainted(const DynInstPtr &inst, int idx) const;
    bool argsTainted(const DynInstPtr &inst) const;
    bool addrTainted(const DynInstPtr &inst) const;

    /** Rename hook: a freshly allocated destination register is secret. */
    void taintRenamedDest(PhysRegIdPtr reg);

    /** IEW hook: must this transmitter be held back right now? */
    bool gateBlocks(const DynInstPtr &inst) const;
    /** IEW hook: bookkeeping when a transmitter is held / released. */
    void noteDelayed(const DynInstPtr &inst);
    void noteReleased(const DynInstPtr &inst);

    /**
     * IEW hook for a detected misprediction: returns true (and records the
     * instruction) if its squash must be deferred (Lazy implicit flow).
     */
    bool deferSquash(const DynInstPtr &inst);
    /** IEW hook: deferred squashes that may now be sent to commit. */
    std::vector<DynInstPtr> takeRaisableSquashes(ThreadID tid);

    /**
     * End-of-cycle update (called from CPU::tick after commit): recompute
     * the visibility point, declassify transmitters at the VP, then
     * propagate untaint.
     */
    void tick();

  private:
    void setTaint(PhysRegIdPtr reg, bool taint);
    bool tracked(PhysRegIdPtr reg) const;
    void updateVisibility(ThreadID tid);
    void propagateUntaint(ThreadID tid);
    bool backwardInvertible(const DynInstPtr &inst) const;

    CPU *cpu;
    const Mode mode;
    const bool futuristic;
    const Untaint untaintMode;
    const unsigned untaintWidth;
    const bool lazyImplicitFlow;

    /** One taint bit per renameable physical register (by flat index). */
    std::vector<uint8_t> taint;
    const unsigned numPhysRegs;

    /** Mispredicted tainted branches whose squash is deferred. */
    std::list<DynInstPtr> pending[MaxThreads];

    struct SPTStats : public statistics::Group
    {
        SPTStats(CPU *cpu);

        statistics::Scalar taintedAtRename;
        statistics::Scalar vpUntaints;
        statistics::Scalar fwdUntaints;
        statistics::Scalar bwdUntaints;
        statistics::Scalar delayedTransmitters;
        statistics::Scalar delayedCycles;
        statistics::Scalar deferredSquashes;
        statistics::Scalar raisedSquashes;
        statistics::Scalar untaintQueueFull;
    } stats;
};

} // namespace o3
} // namespace gem5

#endif // __CPU_O3_SPT_HH__
