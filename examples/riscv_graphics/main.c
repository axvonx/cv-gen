// A small fixed-point raycaster. Rays walk an 8x8 room; wall height is quantized.
typedef unsigned int u32;
typedef unsigned char u8;
#ifndef HOST
#define FRAME ((volatile u8 *)0xf000)
#else
static volatile u8 framebuffer[256];
#define FRAME framebuffer
#endif
volatile u32 initialized = 7;
volatile u32 uninitialized;

static int wall(int x, int y) {
    return x <= 0 || x >= 7 || y <= 0 || y >= 7 || (x == 5 && y <= 5);
}

int main(void) {
    if (initialized != 7 || uninitialized != 0) return -1;
    uninitialized = 1;
#ifndef HOST
    // Check high memory and the last word of the 64 KiB RAM window.
    *(volatile u32 *)0xe100 = 0xdeadbeef;
    *(volatile u32 *)0xfffc = 0x12345678;
    if (*(volatile u32 *)0xe100 != 0xdeadbeef ||
        *(volatile u32 *)0xfffc != 0x12345678) return -2;
#endif
    u32 checksum = 0;
    for (int column = 0; column < 16; ++column) {
        int x = 224, y = 352; // camera (3.5,5.5), coordinates have six fractional bits
        int dx = column - 8;
        u32 distance = 0;
        do {
            x += dx;
            y -= 8;
            ++distance;
        } while (!wall(x >> 6, y >> 6) && distance < 64);
        u32 height = distance < 12 ? 16 : distance < 16 ? 12 :
                     distance < 20 ? 10 : distance < 24 ? 8 : distance < 28 ? 6 : 4;
        u32 top = (16 - height) >> 1;
        u32 shade = 240 - (distance << 2);
        for (u32 row = 0; row < 16; ++row) {
            u8 value = row < top ? 24 : row >= top + height ? 8 : (u8)shade;
            FRAME[(row << 4) + (u32)column] = value;
            checksum += value;
        }
    }
#ifdef HOST
    extern int putchar(int);
    for (u32 i = 0; i < 256; ++i) putchar(FRAME[i]);
    return 0;
#else
    return (int)checksum;
#endif
}
