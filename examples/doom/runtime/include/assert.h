#ifndef _ASSERT_H
#define _ASSERT_H
void __assert_fail(const char *expression, const char *file, int line) __attribute__((noreturn));
#define assert(e) ((e) ? (void)0 : __assert_fail(#e, __FILE__, __LINE__))
#endif
