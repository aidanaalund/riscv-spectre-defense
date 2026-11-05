/* flush_reload_rv.c — single-thread Flush+Reload self-test for RV64GC/gem5.
 *
 * Derived from UT Austin's ECE 382N-Sec Class GitHub at: 
 * https://github.com/ece382n-sec/Example-PoCs/tree/main
 *
 * No speculation here. This validates the cache side channel itself:
 *   1. allocate a 256-line probe array (one cache line per symbol, page-strided)
 *   2. calibrate the cache hit vs. miss latency threshold (in gem5 cycles)
 *   3. flush every line, then deliberately touch ONE "secret" line
 *   4. reload all lines and confirm the touched one is the fastest (a hit)
 *
 * If this prints the correct recovered index with a clear hit/miss gap, the
 * channel + cbo.flush + rdcycle timer all work, and the threshold it prints is
 * reused by the Spectre PoC. Build: see benchmarks/build_benchmarks.sh.
 */
#include "../riscv_asm.h"
#include "../color.h"
#include <assert.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

#define PAGE_SIZE 4096
#define SYMBOL_CNT 256
#define STRIDE 64   /* one cache line; keeps 256-entry probe resident in L1D */

/* Calibrate cache hit/miss threshold using cbo.flush + the cycle timer. */
static uint64_t calibrate_latency(void) {
    uint64_t hit = 0, miss = 0, rep = 1000;
    uint8_t *data = malloc(64);
    assert(data);

    _maccess(data);                       /* warm up */
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

    uint64_t threshold = ((2 * miss) + hit) / 3;
    printf("Avg hit: %" PRIu64 " cyc, avg miss: %" PRIu64 " cyc, threshold: %"
           PRIu64 " cyc\n", hit, miss, threshold);
    free(data);
    return threshold;
}

int main(int argc, char **argv) {
    size_t secret_idx = (argc == 2) ? (size_t)strtoul(argv[1], NULL, 0) : 42;
    secret_idx %= SYMBOL_CNT;

    uint64_t threshold = calibrate_latency();
    printf("-----------------------------------------\n");

    uint8_t *pages = mmap(NULL, STRIDE * SYMBOL_CNT, PROT_READ | PROT_WRITE,
                          MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(pages != MAP_FAILED);
    memset(pages, 1, STRIDE * SYMBOL_CNT);   /* force page allocation */

    uint64_t hits[SYMBOL_CNT] = {0};
    const int REP = 50;
    for (int r = 0; r < REP; r++) {
        /* Flush all probe lines. */
        for (size_t j = 0; j < SYMBOL_CNT; j++)
            _mm_clflush(pages + j * STRIDE);
        _mm_mfence();

        /* "Transmit": touch exactly one line. */
        _maccess(pages + secret_idx * STRIDE);
        _mm_mfence();

        /* "Reload": time every line, count hits. Stride order confuses HW
         * prefetchers (gem5 may model one). */
        for (size_t i = 0; i < SYMBOL_CNT; i++) {
            size_t idx = (i * 167 + 13) % SYMBOL_CNT;
            if (_time_maccess(pages + idx * STRIDE) <= threshold)
                hits[idx]++;
        }
    }

    size_t best = 0;
    for (size_t i = 1; i < SYMBOL_CNT; i++)
        if (hits[i] > hits[best]) best = i;

    printf("Secret index: %zu   Recovered: %zu   hits=%" PRIu64 "/%d\n",
           secret_idx, best, hits[best], REP);
    if (best == secret_idx)
        printf(GREEN_F "CHANNEL OK: recovered the transmitted line\n" RESET_C);
    else
        printf(RED_F "CHANNEL FAIL: mismatch (tune threshold/REP)\n" RESET_C);

    munmap(pages, STRIDE * SYMBOL_CNT);
    return best != secret_idx;
}
