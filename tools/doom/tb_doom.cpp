// Native Verilator testbench for the DOOM machine (examples/doom/rv32_doom.v).
//
// Loads the program and WAD through the RTL loader port, verifies a sample of the
// load through the inspection port, then clocks the machine. At each frame
// doorbell it reads the framebuffer and palette through the inspection port,
// logs the frame exactly as the ISS does, pushes that frame's key events into
// the key FIFO and acknowledges. With -DTRACE (a --public-flat-rw build) it also
// produces the ISS's rolling retire hash and windowed retire trace.
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <memory>

#include "Vrv32_doom.h"
#include "verilated.h"
#ifdef TRACE
#include "Vrv32_doom___024root.h"
#endif

extern "C" {
#include "common.h"
}

static Vrv32_doom *m;
static uint64_t edges;

static void cycle()
{
    m->clk = 1;
    m->eval();
    m->clk = 0;
    m->eval();
    edges++;
}

static uint64_t instret() { return (uint64_t)m->instret_hi << 32 | m->instret_lo; }
static uint64_t cycles() { return (uint64_t)m->cycle_hi << 32 | m->cycle_lo; }

static uint32_t peek(uint32_t address)
{
    m->peek_address = address;
    m->eval();
    return m->peek_word;
}

#ifdef TRACE
static uint32_t reg(unsigned n)
{
    auto *r = m->rootp;
    switch (n) {
#define R(i) case i: return r->rv32_doom__DOT__cpu__DOT__registers__DOT__bank__BRA__##i##__KET____DOT__r__DOT__q;
        R(1) R(2) R(3) R(4) R(5) R(6) R(7) R(8) R(9) R(10) R(11) R(12) R(13) R(14) R(15) R(16)
        R(17) R(18) R(19) R(20) R(21) R(22) R(23) R(24) R(25) R(26) R(27) R(28) R(29) R(30) R(31)
#undef R
    }
    return 0;
}

static int writes_rd(uint32_t insn)
{
    uint32_t opcode = insn & 0x7f;
    return opcode == 0x37 || opcode == 0x17 || opcode == 0x6f || opcode == 0x67 ||
           opcode == 0x13 || opcode == 0x33 || opcode == 0x03;
}
#endif

int main(int argc, char **argv)
{
    options_t o;
    if (parse_options(argc, argv, &o)) return 64;
    auto context = std::make_unique<VerilatedContext>();
    m = new Vrv32_doom{context.get()};
    std::unique_ptr<uint8_t[]> image(new uint8_t[RAM_SIZE]());
    if (load_machine(image.get(), &o)) return 66;
    run_log_t log;
    run_log_open(&log, &o);
    keys_t keys;
    keys_load(&keys, o.keys);

    // Reset low-high-low, as the Super Turbo rv32 profile boots.
    m->clk = 0; m->rst = 0; m->run = 0; m->eval();
    m->rst = 1; m->eval();
    m->rst = 0; m->eval();

    // Load every non-zero word through the loader port (RAM resets to zero).
    auto started = std::chrono::steady_clock::now();
    const uint32_t *words = reinterpret_cast<const uint32_t *>(image.get());
    uint32_t loaded = 0;
    for (uint32_t i = 0; i < RAM_SIZE / 4; i++)
        if (words[i]) {
            m->load_address = i * 4;
            m->load_data = words[i];
            m->eval();
            m->load_enable = 1;
            m->eval();
            m->load_enable = 0;
            m->eval();
            loaded++;
        }
    m->inspect = 1;
    for (uint32_t i = 0; i < RAM_SIZE / 4; i += 997)
        if (peek(i * 4) != words[i]) {
            fprintf(stderr, "load verification failed at %08x\n", i * 4);
            return 70;
        }
    m->inspect = 0;
    m->eval();
    double load_seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    if (!o.quiet) fprintf(stderr, "loaded %u words in %.2fs\n", loaded, load_seconds);

    uint32_t due[KEY_FIFO];
    unsigned n = keys_due(&keys, 0, due);
    for (unsigned i = 0; i < n; i++) {
        m->key_push = 1;
        m->key_data = ((due[i] >> 9 & 1) << 8) | (due[i] & 0xff);
        cycle();
    }
    m->key_push = 0;
    m->eval();

    uint64_t limit = o.max_instret ? o.max_instret : UINT64_MAX;
    uint64_t frames = 0;
    started = std::chrono::steady_clock::now();
    m->run = 1;
    m->eval();
    while (!m->done && !m->fault && instret() < limit) {
        if (m->console_write) run_log_console(&log, (char)m->console_data);
#ifdef TRACE
        uint64_t before = instret();
        uint32_t pc = m->pc, insn = m->instruction;
        cycle();
        if (instret() != before) {
            uint32_t rd = writes_rd(insn) ? (insn >> 7) & 31 : 0;
            run_log_retire(&log, before, pc, insn, rd, rd ? reg(rd) : 0, 0);
        }
#else
        cycle();
#endif
        if (m->frame_pending) {
            frames++;
            m->inspect = 1;
            for (uint32_t a = FRAMEBUFFER; a < FRAMEBUFFER + SCREEN_WIDTH * SCREEN_HEIGHT; a += 4) {
                uint32_t w = peek(a);
                memcpy(image.get() + a, &w, 4);
            }
            for (uint32_t a = PALETTE; a < PALETTE + 768; a += 4) {
                uint32_t w = peek(a);
                memcpy(image.get() + a, &w, 4);
            }
            m->inspect = 0;
            m->eval();
            run_log_frame(&log, frames, m->frame_info, instret(), cycles(), image.get());
            if (o.max_frames && frames >= o.max_frames) break;
            n = keys_due(&keys, (uint32_t)frames, due);
            for (unsigned i = 0; i < n; i++) {
                m->key_push = 1;
                m->key_data = ((due[i] >> 9 & 1) << 8) | (due[i] & 0xff);
                cycle();
            }
            m->key_push = 0;
            m->frame_ack = 1;
            cycle();
            m->frame_ack = 0;
            m->eval();
        }
    }
    double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    int cause = m->fault ? m->fault_cause : 0;
    if (cause)
        fprintf(stderr, "FAULT cause=%d (%s) pc=%08x insn=%08x instret=%llu\n", cause,
                fault_name(cause), m->pc, m->instruction, (unsigned long long)instret());
    run_log_close(&log, m->done ? (int)m->exit_code : -1, cause, m->pc, instret(), cycles(), frames,
                  seconds);
    fprintf(stderr, "%.2f M cycles/s (%llu clock edges)\n", seconds > 0 ? cycles() / seconds / 1e6 : 0,
            (unsigned long long)edges);
    m->final();
    delete m;
    return cause ? 2 : 0;
}
