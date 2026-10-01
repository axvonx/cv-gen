#include "machine.h"
# Reset entry at address 0. Page 0 holds only this code; data accesses there fault.
.section .text.start
.globl _start
_start:
    li sp, STACK_TOP
    la t0, __bss_start
    la t1, __bss_end
1:  bgeu t0, t1, 2f
    sw zero, 0(t0)
    addi t0, t0, 4
    j 1b
2:  call main
    li t0, MMIO_BASE
    sw a0, MMIO_EXIT(t0)
3:  j 3b
