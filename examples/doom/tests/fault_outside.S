/* Expected fault: see test_doom_machine.py */
#include "prelude.h"
    li t0, RAM_SIZE
    lw t1, 0(t0)
    EXIT 0
