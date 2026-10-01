/* Expected fault: see test_doom_machine.py */
#include "prelude.h"
    sh t1, MMIO_CONSOLE(t6)
    EXIT 0
