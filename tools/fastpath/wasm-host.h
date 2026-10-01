// Verilator 5.052 detects CPU_ZERO in Emscripten's compatibility headers as
// Linux affinity support. This single-threaded Worker has no host CPU affinity.
// Load those headers once, then select Verilator's existing portable fallback.
#include <sched.h>
#include <pthread.h>
#undef CPU_ZERO
#undef __linux
#undef __linux__
