/* DOOM's game logic is fixed point; only trivial float helpers are needed. */
#ifndef _MATH_H
#define _MATH_H
static inline double fabs(double x) { return x < 0 ? -x : x; }
#endif
