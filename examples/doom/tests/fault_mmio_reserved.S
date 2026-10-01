/* Expected fault: see test_doom_machine.py */
#include "prelude.h"
    lw t1, 0x14(t6)
    EXIT 0
