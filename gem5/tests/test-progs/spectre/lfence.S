.section .text
.globl _start

_start:
    # Get address of memory location
    la t0, data

    # Older load (should miss if line is cold)
    ld t1, 0(t0)

    # Custom LFENCE
    .word 0x0000000b

    # Younger instruction
    addi t2, zero, 10

    # Exit program (Linux RISC-V syscall)
    li a0, 0
    li a7, 93
    ecall

.section .bss
.balign 64
data:
    .zero 64
