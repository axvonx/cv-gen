/* Cycle/instret MMIO timing, then the instret low/high words across a 16-bit wrap. */
#include "prelude.h"
    lw a1, MMIO_CYCLE_LO(t6)
    lw a2, MMIO_INSTRET_LO(t6)
    addi x0, x0, 0
    lw a3, MMIO_CYCLE_LO(t6)
    lw a4, MMIO_INSTRET_LO(t6)
    sub a3, a3, a1          # 3 + 3 + 2 cycles
    sub a4, a4, a2          # 3 instructions
    slli a3, a3, 8
    or s0, a3, a4           # expect 0x803
    li t0, 40000            # 2 instructions per iteration crosses 65536 retired
1:  addi t0, t0, -1
    bnez t0, 1b
    lw a5, MMIO_INSTRET_LO(t6)
    lw a6, MMIO_INSTRET_HI(t6)
    lw a7, MMIO_CYCLE_HI(t6)
    srli a5, a5, 16          # expect 1 (80000+ retired)
    or a5, a5, a6           # high words stay 0
    or a5, a5, a7
    slli a5, a5, 12
    or a0, s0, a5           # expect 0x1803
    sw a0, MMIO_EXIT(t6)
