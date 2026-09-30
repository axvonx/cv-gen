// Freestanding RV32I: no runtime library or multiply extension required.
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

volatile u32 initialized = 7;
volatile u32 uninitialized;

__attribute__((noinline)) static u32 square(u32 n) {
    volatile u32 total = 0;
    for (u32 i = 0; i < n; ++i) total += n;
    return total;
}

int main(void) {
    if (initialized != 7 || uninitialized != 0) return -3;
    uninitialized = 1;
    volatile u32 values[5];
    u32 sum = 0;
    for (u32 i = 0; i < 5; ++i) {
        values[i] = square(i + 1);
        sum += values[i];
    }
    volatile u32 *word = (volatile u32 *)0x900;
    volatile u8 *bytes = (volatile u8 *)0x900;
    volatile u16 *halves = (volatile u16 *)0x900;
    *word = 0x12345678;
    bytes[1] = 0xab;
    halves[1] = 0xcdef;
    if (*word != 0xcdefab78 || bytes[1] != 0xab || halves[1] != 0xcdef)
        return -1;
    if (*(volatile signed char *)(bytes + 1) != -85 ||
        *(volatile short *)(halves + 1) != -12817) return -2;
    return (int)sum; // 1 + 4 + 9 + 16 + 25 = 55
}
