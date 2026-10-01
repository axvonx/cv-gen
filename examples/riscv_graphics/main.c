// A small fixed-point raycaster. Rays walk an 8x8 room; wall height is quantized.
typedef unsigned int u32;
typedef unsigned char u8;
#ifndef SCREEN
#define SCREEN 16
#endif
_Static_assert(SCREEN == 16 || SCREEN == 64, "supported screen sizes: 16 or 64");
#ifndef HOST
_Static_assert(SCREEN == 16, "the CPU framebuffer currently holds 16x16 pixels");
#define FRAME ((volatile u8 *)0xf000)
#else
static volatile u8 framebuffer[SCREEN * SCREEN];
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
    u32 frame = 0;
    do {
        u32 checksum = 0;
        for (int column = 0; column < SCREEN; ++column) {
            int x = 224 << 2, y = 352 << 2; // eight fractional bits
#ifdef ANIMATE
            // Sweep sideways and back without multiply/divide helpers.
            u32 phase = frame & 31;
            x = (192 << 2) + (int)((phase < 16 ? phase : 31 - phase) << 4);
#endif
            int dx = (column * (64 / SCREEN)) - 32;
            u32 distance = 0;
            do {
                x += dx;
                y -= 32;
                ++distance;
            } while (!wall(x >> 8, y >> 8) && distance < 64);
            u32 height = distance < 12 ? 16 : distance < 16 ? 12 :
                         distance < 20 ? 10 : distance < 24 ? 8 : distance < 28 ? 6 : 4;
            height = (height * SCREEN) >> 4;
            u32 top = (SCREEN - height) >> 1;
            u32 shade = 240 - (distance << 2);
            for (u32 row = 0; row < SCREEN; ++row) {
                u8 value = row < top ? 24 : row >= top + height ? 8 : (u8)shade;
                FRAME[row * SCREEN + (u32)column] = value;
                checksum += value;
            }
        }
#ifdef HOST
        extern int putchar(int);
        for (u32 i = 0; i < SCREEN * SCREEN; ++i) putchar(FRAME[i]);
        ++frame;
#ifdef ANIMATE
    } while (frame < 32);
#else
    } while (0);
#endif
    return 0;
#elif defined(ANIMATE)
        // Publish a completed-frame count; never set done or return to startup.
        *(volatile u32 *)0x10000 = ++frame;
    } while (1);
#else
        return (int)checksum;
    } while (0);
#endif
}
