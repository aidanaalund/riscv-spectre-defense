#include <stdint.h>

#define ARRAY_SIZE (8 * 1024 * 1024)

static uint8_t array[ARRAY_SIZE] __attribute__((aligned(64)));

static inline void lfence(void)
{
    __asm__ __volatile__(".word 0x0000000b" ::: "memory");
}

int main(void)
{
    volatile uint8_t *ptr = &array[4096];

    // Force the array page to be initialized
    *ptr = 42;

    // Flush the cache line (if supported)
    // Not using a flush instruction for now.

    // Older load
    uint8_t value = *ptr;

    // Custom LFENCE
    lfence();

    // Younger instruction
    __asm__ __volatile__("addi x5, x0, 10" ::: "t0");

    return value == 42 ? 0 : 1;
}