/* riscv_asm.h — RV64GC microarchitectural primitives for the Spectre PoCs.
 *
 * Drop-in replacement for the x86 "inline_asm.h"/<x86intrin.h> the original
 * PoCs used. Same primitive names so the ported sources stay close to the
 * x86 originals. Everything here is for the gem5 RV64GC O3 simulation only.
 *
 * Mapping (x86 -> RISC-V):
 *   _mm_clflush   -> cbo.flush      (Zicbom; needs senvcfg.CBCFE in U-mode)
 *   _rdtsc        -> rdcycle        (gem5 returns curCycle())
 *   _mm_mfence    -> fence rw,rw    (memory ordering only)
 *   _mm_lfence    -> spec.fence     (our custom-0 speculation barrier)
 *   _maccess      -> ld             (dependent load so the access is real)
 *
 * Build with: -march=rv64gc_zicbom (cbo.flush) and -static.
 */
#ifndef RISCV_ASM_H
#define RISCV_ASM_H

#include <stdint.h>
#include <stddef.h>

/* ---- memory access: a real dependent load of one byte ---- */
static inline void _maccess(void *p) {
    volatile uint8_t v;
    __asm__ __volatile__("lb %0, 0(%1)\n" : "=r"(v) : "r"(p) : "memory");
    (void)v;
}

/* ---- cache-line flush: Zicbom cbo.flush rs1 (funct ignores rd) ---- */
static inline void _mm_clflush(volatile void *p) {
    /* cbo.flush uses the standard encoding; assemble via .insn so we do not
     * depend on assembler mnemonic support. Equivalent to: cbo.flush 0(rs1) */
    __asm__ __volatile__("cbo.flush 0(%0)\n" : : "r"(p) : "memory");
}

/* ---- memory-ordering fence (NOT a speculation barrier) ---- */
static inline void _mm_mfence(void) {
    __asm__ __volatile__("fence rw, rw\n" ::: "memory");
}

/* ---- speculation barrier: our custom-0 "spec.fence" ---------------------
 * Encoding: custom-0 major opcode (0x0b), funct3=0, rd=rs1=rs2=0 => 0x0000000b
 * In the baseline (no gem5 support) this decodes as a NOP-ish custom op; with
 * the decoder patch it serializes dispatch (IsSerializeAfter|IsNonSpeculative).
 * We emit the raw word via .insn so a stock assembler accepts it.          */
static inline void _spec_fence(void) {
    __asm__ __volatile__(".insn r 0x0b, 0, 0, x0, x0, x0\n" ::: "memory");
}

/* _mm_lfence: in the x86 PoCs this is used by the ATTACKER purely to order the
 * flushes before the victim call. That ordering role must always happen, so we
 * map it to a plain memory-ordering fence (not the speculation barrier). The
 * Spectre DEFENSE is a separate barrier placed inside the victim, below. */
static inline void _mm_lfence(void) {
    __asm__ __volatile__("fence rw, rw\n" ::: "memory");
}

/* SPEC_BARRIER: the actual defense. Placed in the victim right after a bounds
 * check. Compiled in only for the "lfence" build variant (-DUSE_LFENCE); in the
 * baseline build it vanishes so the Spectre gadget speculates and leaks. */
#ifdef USE_LFENCE
#define SPEC_BARRIER() _spec_fence()
#else
#define SPEC_BARRIER() ((void)0)
#endif

/* ---- cycle counter ---- */
static inline uint64_t _rdtsc(void) {
    uint64_t c;
    __asm__ __volatile__("rdcycle %0\n" : "=r"(c));
    return c;
}

/* Fenced timer start/end so the measured region is well-ordered. */
static inline uint64_t _timer_start(void) {
    uint64_t c;
    __asm__ __volatile__("fence rw, rw\n rdcycle %0\n fence rw, rw\n" : "=r"(c));
    return c;
}
static inline uint64_t _timer_end(void) {
    uint64_t c;
    __asm__ __volatile__("fence rw, rw\n rdcycle %0\n fence rw, rw\n" : "=r"(c));
    return c;
}

/* Time a single access (load) to *p in cycles. */
static inline uint64_t _time_maccess(void *p) {
    uint64_t start = _timer_start();
    _maccess(p);
    return _timer_end() - start;
}

/* Prevent the compiler from optimizing away a value. */
#define _no_opt(x) __asm__ __volatile__("" : : "r"(x) : "memory")

#endif /* RISCV_ASM_H */
