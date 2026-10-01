/* Expected fault: see test_doom_machine.py */
#include "prelude.h"
    li t0, NULL_GUARD - 4
    sw zero, 0(t0)
    EXIT 0
