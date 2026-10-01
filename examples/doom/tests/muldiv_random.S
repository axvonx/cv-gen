/* 2048 pseudo-random operand pairs (xorshift32, seed 0x2545f491) through all eight
   RV32M instructions: a = next, b = next >> (next & 31). Printed like muldiv.S. */
#include "prelude.h"
    li s1, 0x2545f491        # xorshift32 state
    li s2, 2048
loop:
    jal ra, next
    mv s4, a0
    jal ra, next
    mv s5, a0
    jal ra, next
    andi a0, a0, 31
    srl s5, s5, a0
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
    addi s2, s2, -1
    bnez s2, loop
    EXIT 0

next:
    slli t0, s1, 13
    xor s1, s1, t0
    srli t0, s1, 17
    xor s1, s1, t0
    slli t0, s1, 5
    xor s1, s1, t0
    mv a0, s1
    ret

print:
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
