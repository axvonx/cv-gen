/* Expected fault: see test_doom_machine.py */
#include "prelude.h"
    lw t1, 16(zero)
    EXIT 0
