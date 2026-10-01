/* Word, halfword and byte accesses on both sides of every 4 MiB bank boundary
   and the top of RAM; exit code 0 on success, else the failing check number. */
#include "prelude.h"
    la s0, addresses
    li s1, 0                 # check number
2:  lw a0, 0(s0)
    beqz a0, 3f
    xori a1, a0, 0x5a5      # word pattern derived from the address
    sw a1, 0(a0)
    addi s0, s0, 4
    j 2b
3:  la s0, addresses
4:  lw a0, 0(s0)
    beqz a0, 5f
    addi s1, s1, 1
    lw a2, 0(a0)
    xori a1, a0, 0x5a5
    bne a1, a2, fail
    addi s0, s0, 4
    j 4b
5:  li a0, 0x3ffffc          # byte lanes and sign extension across bank 0/1
    li t0, 0x80
    sb t0, 3(a0)
    li t0, 0x7f
    sb t0, 4(a0)
    addi s1, s1, 1
    lb t1, 3(a0)
    li t2, -128
    bne t1, t2, fail
    addi s1, s1, 1
    lbu t1, 3(a0)
    li t2, 0x80
    bne t1, t2, fail
    li t0, 0x8001
    sh t0, 2(a0)
    addi s1, s1, 1
    lh t1, 2(a0)
    li t2, -32767
    bne t1, t2, fail
    addi s1, s1, 1
    lhu t1, 2(a0)
    li t2, 0x8001
    bne t1, t2, fail
    addi s1, s1, 1
    lw t1, 0(a0)             # bytes 0,1 keep the earlier word pattern
    xori t2, a0, 0x5a5
    li t3, 0xffff
    and t2, t2, t3
    li t3, 0x80010000
    or t2, t2, t3
    bne t1, t2, fail
    addi s1, s1, 1
    lbu t1, 4(a0)
    li t2, 0x7f
    bne t1, t2, fail
    EXIT 0
fail:
    sw s1, MMIO_EXIT(t6)
.section .rodata
.p2align 2
addresses:
    .word 0x10000, 0x3ffffc, 0x400000, 0x7ffffc, 0x800000, 0xbffffc, 0xc00000, 0xfffffc, 0
