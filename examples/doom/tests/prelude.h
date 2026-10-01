/* Shared by the directed machine tests: entry at 0, t6 = MMIO base. */
#include "machine.h"
.macro EXIT code
    li t5, \code
    sw t5, MMIO_EXIT(t6)
.endm
.macro PUTC char
    li t5, \char
    sw t5, MMIO_CONSOLE(t6)
.endm
.section .text.start
.globl _start
_start:
    li t6, MMIO_BASE
    li sp, STACK_TOP
