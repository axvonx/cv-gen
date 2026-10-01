/* Every pair of edge-case operands through all eight RV32M instructions; each
   result is printed as eight hex digits. test_doom_machine.py checks the console. */
#include "prelude.h"
    la s0, operands
    li s2, 0                 # i
outer:
    li s3, 0                 # j
inner:
    slli t0, s2, 2
    add t0, s0, t0
    lw s4, 0(t0)             # a
    slli t0, s3, 2
    add t0, s0, t0
    lw s5, 0(t0)             # b
    mul a0, s4, s5
    jal ra, print
    mulh a0, s4, s5
    jal ra, print
    mulhsu a0, s4, s5
    jal ra, print
    mulhu a0, s4, s5
    jal ra, print
    div a0, s4, s5
    jal ra, print
    divu a0, s4, s5
    jal ra, print
    rem a0, s4, s5
    jal ra, print
    remu a0, s4, s5
    jal ra, print
    PUTC '\n'
    addi s3, s3, 1
    li t0, 16
    blt s3, t0, inner
    addi s2, s2, 1
    blt s2, t0, outer
    EXIT 0

print:                       # a0 as eight hex digits and a space
    li t1, 28
1:  srl t0, a0, t1
    andi t0, t0, 15
    li t2, 10
    blt t0, t2, 2f
    addi t0, t0, 'a' - '0' - 10
2:  addi t0, t0, '0'
    sw t0, MMIO_CONSOLE(t6)
    addi t1, t1, -4
    bgez t1, 1b
    PUTC ' '
    ret

.section .rodata
.p2align 2
operands:
    .word 0, 1, 0xffffffff, 2, 0xfffffffe, 0x7fffffff, 0x80000000, 0x80000001
    .word 0xffff, 0x10000, 0x12345678, 0xdeadbeef, 3, 0xfffffffd, 0x0001ffff, 0xfffe0001
