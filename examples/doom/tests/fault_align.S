/* Expected fault: see test_doom_machine.py */
#include "prelude.h"
    li t0, 0x2001
    lw t1, 0(t0)
    EXIT 0
