/* Drains the key FIFO at start and after each of two frame doorbells, printing
   each entry as three hex digits and a frame marker. */
#include "prelude.h"
    li s0, 0
next:
    lw a0, MMIO_KEY(t6)
    andi t0, a0, 0x100
    beqz t0, frame
    sw zero, MMIO_KEY_ACK(t6)
    li s1, 8
digit:
    srl t0, a0, s1
    andi t0, t0, 15
    li t1, 10
    blt t0, t1, 1f
    addi t0, t0, 'a' - '0' - 10
1:  addi t0, t0, '0'
    sw t0, MMIO_CONSOLE(t6)
    addi s1, s1, -4
    bgez s1, digit
    PUTC ' '
    j next
frame:
    PUTC '|'
    li t0, 2
    beq s0, t0, done
    addi s0, s0, 1
    sw s0, MMIO_FRAME(t6)
    j next
done:
    EXIT 0
