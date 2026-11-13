/*
 * Cross-core Flush+Reload channel control for RISC-V gem5 FS.
 *
 * Core 0: Victim accesses a shared byte on selected trials.
 * Core 1: Attacker flushes and reloads the byte.
 *
 * No speculative execution in this test.
 *
 * Uses the same helpers as the original Spectre PoC:
 * - cbo.flush
 * - rdcycle
 * - fence rw,rw
 */

 #define _GNU_SOURCE

 #include "../riscv_asm.h"
 
 #include <pthread.h>
 #include <sched.h>
 #include <stdint.h>
 #include <stdio.h>
 #include <stdlib.h>
 #include <string.h>
 #include <errno.h>
 #include <inttypes.h>
 
 #define NTRIALS 200
 #define CACHELINE 64
 
 static uint8_t *line;
 static volatile uint8_t victim_sink;
 
 static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
 static pthread_cond_t requested = PTHREAD_COND_INITIALIZER;
 static pthread_cond_t completed = PTHREAD_COND_INITIALIZER;
 
 static int request_pending;
 static int request_done;
 static int should_access;
 static int stop_worker;
 
 
 /* Pin calling thread to a specific Linux CPU. */
 static void pin_cpu(int cpu) {
     cpu_set_t set;
 
     CPU_ZERO(&set);
     CPU_SET(cpu, &set);
 
     int e = pthread_setaffinity_np(
         pthread_self(),
         sizeof(set),
         &set
     );
 
     if (e) {
         fprintf(
             stderr,
             "pin CPU %d: %s\n",
             cpu,
             strerror(e)
         );
         exit(1);
     }
 
     printf(
         "Pinned requested CPU %d; currently on CPU %d\n",
         cpu,
         sched_getcpu()
     );
 }
 
 
 /* Victim thread: runs on core 0. */
 static void *victim_main(void *unused) {
     (void)unused;
 
     pin_cpu(0);
 
     pthread_mutex_lock(&lock);
 
     for (;;) {
         /* Wait for the attacker to request an operation. */
         while (!request_pending && !stop_worker) {
             pthread_cond_wait(&requested, &lock);
         }
 
         if (stop_worker) {
             break;
         }
 
         int access = should_access;
 
         pthread_mutex_unlock(&lock);
 
         /* Victim accesses the shared line if requested. */
         if (access) {
             victim_sink ^= *(volatile uint8_t *)line;
         }
 
         pthread_mutex_lock(&lock);
 
         request_pending = 0;
         request_done = 1;
 
         pthread_cond_signal(&completed);
     }
 
     pthread_mutex_unlock(&lock);
 
     return NULL;
 }
 
 
 /* Attacker requests a victim operation and waits for completion. */
 static void ask_victim(int access) {
     pthread_mutex_lock(&lock);
 
     should_access = access;
     request_done = 0;
     request_pending = 1;
 
     pthread_cond_signal(&requested);
 
     while (!request_done) {
         pthread_cond_wait(&completed, &lock);
     }
 
     pthread_mutex_unlock(&lock);
 }
 
 
 /* Comparator for sorting cycle measurements. */
 static int cmp_u64(const void *a, const void *b) {
     uint64_t x = *(const uint64_t *)a;
     uint64_t y = *(const uint64_t *)b;
 
     return (x > y) - (x < y);
 }
 
 
 int main(void) {
     /* Main thread is the attacker, running on core 1. */
     pin_cpu(1);
 
     /* Allocate a cache-line-aligned shared region. */
     if (posix_memalign(
         (void **)&line,
         CACHELINE,
         CACHELINE
     )) {
         perror("posix_memalign");
         return 1;
     }
 
     memset(line, 1, CACHELINE);
 
     /* Start the victim thread. */
     pthread_t victim;
 
     int e = pthread_create(
         &victim,
         NULL,
         victim_main,
         NULL
     );
 
     if (e) {
         fprintf(
             stderr,
             "pthread_create: %s\n",
             strerror(e)
         );
         return 1;
     }
 
     uint64_t access_times[NTRIALS / 2];
     uint64_t idle_times[NTRIALS / 2];
 
     /*
      * Alternating trials:
      *
      * Even: victim does NOT access the line.
      * Odd:  victim DOES access the line.
      */
     for (int i = 0; i < NTRIALS; ++i) {
         int access = i & 1;
 
         /* Attacker flushes the shared line. */
         _mm_clflush(line);
         _mm_mfence();
 
         /* Ask the victim to access or ignore the line. */
         ask_victim(access);
 
         /* Attacker measures reload latency. */
         uint64_t start = _timer_start();
 
         _maccess(line);
 
         uint64_t dt = _timer_end() - start;
 
         if (access) {
             access_times[i / 2] = dt;
         } else {
             idle_times[i / 2] = dt;
         }
     }
 
     /* Sort measurements so we can compute medians. */
     qsort(
         access_times,
         NTRIALS / 2,
         sizeof(uint64_t),
         cmp_u64
     );
 
     qsort(
         idle_times,
         NTRIALS / 2,
         sizeof(uint64_t),
         cmp_u64
     );
 
     uint64_t hit = access_times[NTRIALS / 4];
     uint64_t miss = idle_times[NTRIALS / 4];
 
     uint64_t threshold = hit / 2 + miss / 2;
 
     if (hit >= miss) {
         fprintf(
             stderr,
             "WARNING: victim-access median is not faster "
             "than idle median; no confirmed cross-core "
             "cache signal.\n"
         );
     }
 
     int fast_if_accessed = 0;
     int fast_if_idle = 0;
 
     for (int i = 0; i < NTRIALS / 2; ++i) {
         fast_if_accessed += access_times[i] <= threshold;
         fast_if_idle += idle_times[i] <= threshold;
     }
 
     printf(
         "Victim-access median: %" PRIu64 " cycles\n",
         hit
     );
 
     printf(
         "Victim-idle   median: %" PRIu64 " cycles\n",
         miss
     );
 
     printf(
         "Midpoint threshold : %" PRIu64 " cycles\n",
         threshold
     );
 
     printf(
         "Fast after victim access: %d/%d\n",
         fast_if_accessed,
         NTRIALS / 2
     );
 
     printf(
         "Fast without victim access: %d/%d\n",
         fast_if_idle,
         NTRIALS / 2
     );
 
     printf(
         "Interpretation: access should be measurably faster "
         "than idle; otherwise the cross-core channel is "
         "not validated.\n"
     );
 
     /* Stop and join the victim thread. */
     pthread_mutex_lock(&lock);
 
     stop_worker = 1;
     pthread_cond_signal(&requested);
 
     pthread_mutex_unlock(&lock);
 
     pthread_join(victim, NULL);
 
     free(line);
 
     return hit < miss ? 0 : 2;
 }
 