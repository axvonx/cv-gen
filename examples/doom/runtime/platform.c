/* doomgeneric platform hooks for the DOOM machine (and, with DOOM_HOST, the host
   reference build). Runs are deterministic: the engine runs exactly one game tic
   per rendered frame (singletics, as in -timedemo), and the virtual clock used by
   the screen wipe advances only when the engine sleeps. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "doomgeneric.h"
#include "doomstat.h"
#include "i_video.h"
#include "machine.h"

static uint32_t now_ms;
extern boolean singletics;

#ifdef DOOM_HOST
#include "host.h"
#else
#define MMIO(offset) (*(volatile uint32_t *)(MMIO_BASE + (offset)))
#endif

void DG_Init(void)
{
    singletics = true;
#ifndef DOOM_HOST
    DG_ScreenBuffer = (pixel_t *)FRAMEBUFFER;
#else
    host_init();
#endif
}

void DG_DrawFrame(void)
{
    if (palette_changed) {
#ifdef DOOM_HOST
        uint8_t *palette = host_palette;
#else
        uint8_t *palette = (uint8_t *)PALETTE;
#endif
        for (int i = 0; i < 256; i++) {
            palette[i * 3] = colors[i].r;
            palette[i * 3 + 1] = colors[i].g;
            palette[i * 3 + 2] = colors[i].b;
        }
        palette_changed = false;
    }
    uint32_t info = FRAME_INFO(gamestate, menuactive, gametic);
#ifdef DOOM_HOST
    host_frame(info);
#else
    MMIO(MMIO_FRAME) = info;
#endif
}

void DG_SleepMs(uint32_t ms)
{
    now_ms += ms;
}

uint32_t DG_GetTicksMs(void)
{
    return now_ms;
}

int DG_GetKey(int *pressed, unsigned char *key)
{
#ifdef DOOM_HOST
    uint32_t value = host_key();
#else
    uint32_t value = MMIO(MMIO_KEY);
#endif
    if (!(value & 0x100)) return 0;
    *pressed = (value >> 9) & 1;
    *key = (unsigned char)value;
#ifndef DOOM_HOST
    MMIO(MMIO_KEY_ACK) = 1;
#endif
    return 1;
}

void DG_SetWindowTitle(const char *title)
{
    (void)title;
}

int main(int argc, char **argv)
{
#ifdef DOOM_HOST
    host_args(&argc, &argv);
#else
    static char *arguments[] = {"doom", "-iwad", "doom1.wad", "-warp", "1", "1", NULL};
    argc = 6;
    argv = arguments;
#endif
    doomgeneric_Create(argc, argv);
    for (;;) doomgeneric_Tick();
}
