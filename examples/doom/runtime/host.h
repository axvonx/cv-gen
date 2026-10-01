/* Host reference build of the DOOM machine platform: the same engine and platform
   code compiled natively, with the screen and palette placed in a RAM-shaped buffer
   so frames are hashed and logged exactly like the ISS and the RTL testbench. */
#include <stdlib.h>

#include "../../../tools/doom/common.h"

static uint8_t *host_ram;
static uint8_t *host_palette;
static options_t host_options;
static run_log_t host_log;
static keys_t host_keys;
static uint64_t host_frames;

static void host_args(int *argc, char ***argv)
{
    if (parse_options(*argc, *argv, &host_options)) exit(64);
    host_ram = calloc(1, RAM_SIZE);
    host_palette = host_ram + PALETTE;
    run_log_open(&host_log, &host_options);
    keys_load(&host_keys, host_options.keys);
    keys_frame(&host_keys, 0);
    static char *arguments[] = {"doom", "-iwad", NULL, "-warp", "1", "1", NULL};
    arguments[2] = (char *)host_options.wad;
    *argc = 6;
    *argv = arguments;
}

static void host_init(void)
{
    DG_ScreenBuffer = (pixel_t *)(host_ram + FRAMEBUFFER);
}

static void host_frame(uint32_t info)
{
    host_frames++;
    run_log_frame(&host_log, host_frames, info, 0, 0, host_ram);
    keys_frame(&host_keys, (uint32_t)host_frames);
    if (host_options.max_frames && host_frames >= host_options.max_frames) {
        run_log_close(&host_log, -1, 0, 0, 0, 0, host_frames, 0);
        exit(0);
    }
}

static uint32_t host_key(void)
{
    uint32_t value = keys_peek(&host_keys);
    keys_pop(&host_keys);
    return value;
}
