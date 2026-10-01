/* Harness shared by the ISS oracle (iss.c) and the Verilator testbench
 * (tb_doom.cpp): options, machine loading, key schedule and run logs, so the
 * two report in identical formats and can be diffed directly. */
#ifndef DOOM_COMMON_H
#define DOOM_COMMON_H

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "../../examples/doom/runtime/machine.h"

typedef struct {
    const char *image, *wad, *out, *keys, *profile; /* profile: llvm-nm -n -S symbols */
    uint64_t max_instret, max_frames;
    uint64_t dump_from, dump_every;     /* PPM frames; dump_every 0 disables */
    uint64_t checkpoint_every;          /* rolling-hash checkpoint interval */
    uint64_t trace_from, trace_count;   /* retire trace window */
    int quiet;
} options_t;

static const char *fault_name(int cause)
{
    static const char *names[] = {"none", "illegal", "fetch", "align", "access", "mmio"};
    return cause >= 0 && cause <= FAULT_MMIO ? names[cause] : "unknown";
}

static int parse_options(int argc, char **argv, options_t *o)
{
    memset(o, 0, sizeof *o);
    o->image = "build/doom/out/doom.bin";
    o->wad = "build/doom/doom1.wad";
    o->out = "build/doom/run";
    o->checkpoint_every = 1u << 24;
    for (int i = 1; i < argc; i++) {
        const char *k = argv[i], *v = i + 1 < argc ? argv[i + 1] : NULL;
#define NUMBER(name, field) if (!strcmp(k, name) && v) { o->field = strtoull(v, NULL, 0); i++; continue; }
#define STRING(name, field) if (!strcmp(k, name) && v) { o->field = v; i++; continue; }
        STRING("--image", image) STRING("--wad", wad) STRING("--out", out) STRING("--keys", keys)
        STRING("--profile", profile)
        NUMBER("--max-instret", max_instret) NUMBER("--frames", max_frames)
        NUMBER("--dump-from", dump_from) NUMBER("--dump-every", dump_every)
        NUMBER("--checkpoint-every", checkpoint_every)
        NUMBER("--trace-from", trace_from) NUMBER("--trace-count", trace_count)
        if (!strcmp(k, "--quiet")) { o->quiet = 1; continue; }
        fprintf(stderr, "usage: %s [--image F] [--wad F] [--out DIR] [--keys F] [--frames N]\n"
                "  [--max-instret N] [--dump-from N --dump-every N] [--checkpoint-every N]\n"
                "  [--trace-from N --trace-count N] [--profile SYMS] [--quiet]\n", argv[0]);
        return 1;
    }
    return 0;
}

static long read_file(const char *path, uint8_t *to, long capacity)
{
    FILE *f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", path); return -1; }
    long n = (long)fread(to, 1, (size_t)capacity, f);
    int more = fgetc(f) != EOF;
    fclose(f);
    if (more) { fprintf(stderr, "%s does not fit\n", path); return -1; }
    return n;
}

/* Fills a zeroed RAM image: program at 0, WAD header and file at WAD_HEADER. */
static int load_machine(uint8_t *ram, const options_t *o)
{
    if (read_file(o->image, ram, WAD_HEADER) < 0) return 1;
    long wad = read_file(o->wad, ram + WAD_DATA, FRAMEBUFFER - WAD_DATA);
    if (wad < 0) return 1;
    uint32_t header[2] = {WAD_MAGIC, (uint32_t)wad};
    memcpy(ram + WAD_HEADER, header, sizeof header);
    return 0;
}

/* ---- key schedule: "frame pressed key" lines; events for frame N enter the
   FIFO after doorbell N (frame 0: before execution starts) ---- */

#define KEY_FIFO 8
typedef struct { uint32_t frame, value; } key_event_t;
typedef struct {
    key_event_t *events;
    size_t count, next;
    uint32_t fifo[KEY_FIFO];
    unsigned head, size;
} keys_t;

static void keys_load(keys_t *k, const char *path)
{
    memset(k, 0, sizeof *k);
    if (!path) return;
    FILE *f = fopen(path, "r");
    if (!f) { fprintf(stderr, "cannot open %s\n", path); exit(66); }
    char line[256];
    size_t capacity = 0;
    while (fgets(line, sizeof line, f)) {
        char *p = line;
        while (*p == ' ' || *p == '\t') p++;
        if (*p == '#' || *p == '\n' || !*p) continue;
        unsigned long frame = strtoul(p, &p, 0), pressed = strtoul(p, &p, 0), key = strtoul(p, &p, 0);
        if (k->count == capacity) {
            capacity = capacity ? capacity * 2 : 64;
            k->events = (key_event_t *)realloc(k->events, capacity * sizeof *k->events);
        }
        if (k->count && frame < k->events[k->count - 1].frame) {
            fprintf(stderr, "%s: key events must be in frame order\n", path);
            exit(65);
        }
        k->events[k->count++] = (key_event_t){(uint32_t)frame, (uint32_t)(0x100u | (pressed ? 0x200u : 0) | (key & 0xff))};
    }
    fclose(f);
}

/* Returns the events (up to KEY_FIFO) due at this frame boundary, for pushing. */
static unsigned keys_due(keys_t *k, uint32_t frame, uint32_t *values)
{
    unsigned n = 0;
    while (k->next < k->count && k->events[k->next].frame <= frame) {
        if (n == KEY_FIFO) { fprintf(stderr, "more than %d key events at frame %u\n", KEY_FIFO, frame); exit(65); }
        values[n++] = k->events[k->next++].value;
    }
    return n;
}

static void keys_frame(keys_t *k, uint32_t frame)
{
    uint32_t values[KEY_FIFO];
    unsigned n = keys_due(k, frame, values);
    for (unsigned i = 0; i < n; i++) {
        if (k->size == KEY_FIFO) { fprintf(stderr, "key FIFO overflow at frame %u\n", frame); exit(65); }
        k->fifo[(k->head + k->size++) % KEY_FIFO] = values[i];
    }
}

static uint32_t keys_peek(const keys_t *k) { return k->size ? k->fifo[k->head] : 0; }
static void keys_pop(keys_t *k) { if (k->size) { k->head = (k->head + 1) % KEY_FIFO; k->size--; } }

/* ---- run log ---- */

typedef struct {
    const options_t *o;
    FILE *console, *frames, *checkpoints, *trace;
    uint64_t hash, next_checkpoint;
    uint32_t heap_high, stack_low;
    uint64_t first_gameplay_frame, first_gameplay_instret, first_gameplay_cycles;
    int level_tic; /* gametic of the first level frame; -1 until seen */
} run_log_t;

static FILE *open_out(const options_t *o, const char *name)
{
    char path[1024];
    snprintf(path, sizeof path, "%s/%s", o->out, name);
    FILE *f = fopen(path, "w");
    if (!f) { fprintf(stderr, "cannot write %s\n", path); exit(73); }
    return f;
}

static void run_log_open(run_log_t *log, const options_t *o)
{
    memset(log, 0, sizeof *log);
    log->o = o;
    if (mkdir(o->out, 0755) && errno != EEXIST) { fprintf(stderr, "cannot create %s\n", o->out); exit(73); }
    log->console = open_out(o, "console.txt");
    log->frames = open_out(o, "frames.tsv");
    fprintf(log->frames, "frame\tstate\tmenu\ttic\tinstret\tcycles\thash\n");
    log->checkpoints = open_out(o, "checkpoints.txt");
    if (o->trace_count) log->trace = open_out(o, "trace.txt");
    log->hash = 1469598103934665603ull;
    log->next_checkpoint = o->checkpoint_every;
    log->stack_low = STACK_TOP;
    log->level_tic = -1;
}

static void run_log_console(run_log_t *log, char c)
{
    fputc(c, log->console);
    if (!log->o->quiet) fputc(c, stdout);
}

static uint64_t fnv(uint64_t h, const uint8_t *p, size_t n)
{
    for (size_t i = 0; i < n; i++) h = (h ^ p[i]) * 1099511628211ull;
    return h;
}

static void run_log_frame(run_log_t *log, uint64_t frame, uint32_t info, uint64_t instret,
                          uint64_t cycles, const uint8_t *ram)
{
    const uint8_t *pixels = ram + FRAMEBUFFER, *palette = ram + PALETTE;
    uint64_t h = fnv(fnv(1469598103934665603ull, pixels, SCREEN_WIDTH * SCREEN_HEIGHT), palette, 768);
    unsigned state = info >> 28, menu = (info >> 27) & 1, tic = info & 0x07ffffff;
    fprintf(log->frames, "%" PRIu64 "\t%u\t%u\t%u\t%" PRIu64 "\t%" PRIu64 "\t%016" PRIx64 "\n",
            frame, state, menu, tic, instret, cycles, h);
    fflush(log->frames);
    /* Gameplay: a level frame (GS_LEVEL, no menu) after game time has advanced
       past the level's first frame, so wipe frames do not count. */
    if (state == 0 && !menu && log->level_tic < 0) log->level_tic = (int)tic;
    if (!log->first_gameplay_frame && state == 0 && !menu && (int)tic > log->level_tic) {
        log->first_gameplay_frame = frame;
        log->first_gameplay_instret = instret;
        log->first_gameplay_cycles = cycles;
    }
    const options_t *o = log->o;
    if (o->dump_every && frame >= o->dump_from && (frame - o->dump_from) % o->dump_every == 0) {
        char name[64];
        snprintf(name, sizeof name, "frame-%06" PRIu64 ".ppm", frame);
        FILE *f = open_out(o, name);
        fprintf(f, "P6\n%d %d\n255\n", SCREEN_WIDTH, SCREEN_HEIGHT);
        for (int i = 0; i < SCREEN_WIDTH * SCREEN_HEIGHT; i++) fwrite(palette + pixels[i] * 3, 1, 3, f);
        fclose(f);
    }
    if (!o->quiet) fprintf(stderr, "[frame %" PRIu64 " state=%u menu=%u tic=%u instret=%" PRIu64 "]\n",
                           frame, state, menu, tic, instret);
}

static inline void run_log_store(run_log_t *log, uint32_t address)
{
    if (address < HEAP_LIMIT) { if (address > log->heap_high) log->heap_high = address; }
    else if (address < STACK_TOP && address < log->stack_low) log->stack_low = address;
}

/* Called for every retired instruction, before instret is incremented. */
static inline void run_log_retire(run_log_t *log, uint64_t instret, uint32_t pc, uint32_t insn,
                                  uint32_t rd, uint32_t value, uint32_t sp)
{
    (void)sp;
    uint64_t h = log->hash;
    h = (h ^ pc) * 1099511628211ull;
    h = (h ^ (rd ? value ^ (rd << 27) : 0)) * 1099511628211ull;
    log->hash = h;
    if (instret + 1 == log->next_checkpoint) {
        fprintf(log->checkpoints, "%" PRIu64 " %016" PRIx64 "\n", instret + 1, h);
        log->next_checkpoint += log->o->checkpoint_every;
    }
    if (log->trace && instret >= log->o->trace_from && instret - log->o->trace_from < log->o->trace_count)
        fprintf(log->trace, "%" PRIu64 " %08x %08x %u %08x\n", instret, pc, insn, rd, rd ? value : 0);
}

static void run_log_close(run_log_t *log, int exit_code, int cause, uint32_t pc, uint64_t instret,
                          uint64_t cycles, uint64_t frames, double seconds)
{
    /* Store addresses are tracked only by the ISS; the testbench reports null. */
    char heap[16] = "null", stack[16] = "null";
    if (log->heap_high) snprintf(heap, sizeof heap, "\"0x%08x\"", log->heap_high);
    if (log->stack_low != STACK_TOP) snprintf(stack, sizeof stack, "\"0x%08x\"", log->stack_low);
    FILE *f = open_out(log->o, "summary.json");
    fprintf(f, "{\n  \"exit_code\": %d,\n  \"fault\": \"%s\",\n  \"pc\": \"0x%08x\",\n"
            "  \"instret\": %" PRIu64 ",\n  \"cycles\": %" PRIu64 ",\n  \"frames\": %" PRIu64 ",\n"
            "  \"first_gameplay_frame\": %" PRIu64 ",\n  \"first_gameplay_instret\": %" PRIu64 ",\n"
            "  \"first_gameplay_cycles\": %" PRIu64 ",\n"
            "  \"heap_high_water\": %s,\n  \"stack_low_water\": %s,\n"
            "  \"final_hash\": \"%016" PRIx64 "\",\n  \"host_seconds\": %.3f\n}\n",
            exit_code, fault_name(cause), pc, instret, cycles, frames, log->first_gameplay_frame,
            log->first_gameplay_instret, log->first_gameplay_cycles, heap, stack,
            log->hash, seconds);
    fclose(f);
    fprintf(log->checkpoints, "%" PRIu64 " %016" PRIx64 " final\n", instret, log->hash);
    fclose(log->console);
    fclose(log->frames);
    fclose(log->checkpoints);
    if (log->trace) fclose(log->trace);
    fprintf(stderr, "instret=%" PRIu64 " cycles=%" PRIu64 " frames=%" PRIu64 " fault=%s exit=%d "
            "%.2fs (%.1f M instr/s)\n", instret, cycles, frames, fault_name(cause), exit_code, seconds,
            seconds > 0 ? instret / seconds / 1e6 : 0);
}

#endif
