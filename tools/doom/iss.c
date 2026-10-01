/* Reference RV32I instruction-set simulator for the DOOM machine.
 *
 * A test oracle only: DOOM's deliverable runs on the RTL. It mirrors the RTL's
 * instruction legality (examples/riscv/rv32_decode.v plus RV32M from
 * rv32_muldiv.v, which also takes two cycles), its 2/3-cycle timing,
 * the memory map and MMIO in examples/doom/runtime/machine.h, and the frame
 * handshake: a doorbell write ends a frame, after which the key events
 * scheduled for that frame enter the key FIFO before execution resumes.
 *
 * Outputs: console text, a frame log (index, info, instret, cycles, hash),
 * optional PPM frames, rolling-hash checkpoints and windowed retire traces
 * in the same text format as the Verilator testbench.
 */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "../../examples/doom/runtime/machine.h"
#include "common.h"

static uint8_t *ram;
static uint32_t x[32], pc;
static uint64_t instret, cycles;

/* A fault ends the faulting instruction after its FETCH cycle (fetch faults)
   or its EXECUTE cycle (everything else), as on the RTL. */
static int fault(int cause, uint32_t instruction)
{
    cycles += cause == FAULT_FETCH ? 1 : 2;
    fprintf(stderr, "FAULT cause=%d (%s) pc=%08" PRIx32 " insn=%08" PRIx32 " instret=%" PRIu64 "\n",
            cause, fault_name(cause), pc, instruction, instret);
    return cause;
}

static inline uint32_t load32(uint32_t a) { uint32_t v; memcpy(&v, ram + a, 4); return v; }

/* --profile: retired instructions and cycles per function, from llvm-nm -n -S. */
static uint32_t *profile_instret, *profile_cycles;

typedef struct { uint32_t start, size; char name[96]; uint64_t instret, cycles; } symbol_t;

static int by_instret(const void *a, const void *b)
{
    const symbol_t *x = a, *y = b;
    return x->cycles < y->cycles ? 1 : x->cycles > y->cycles ? -1 : 0;
}

static void write_profile(const options_t *o, uint64_t total_instret, uint64_t total_cycles)
{
    FILE *f = fopen(o->profile, "r");
    if (!f) { fprintf(stderr, "cannot open %s\n", o->profile); return; }
    symbol_t *symbols = NULL;
    size_t count = 0, capacity = 0;
    char line[512], type;
    unsigned start, size;
    char name[400];
    int pending = 0; /* last symbol is sizeless: it extends to the next symbol of any kind */
    while (fgets(line, sizeof line, f)) {
        /* Sized lines are "addr size type name", assembly symbols "addr type name". */
        int fields = sscanf(line, "%x %x %c %399s", &start, &size, &type, name);
        if (fields != 4) {
            if (sscanf(line, "%x %c %399s", &start, &type, name) != 3) continue;
            size = 0;
        }
        if (pending && start > symbols[count - 1].start) {
            symbols[count - 1].size = start - symbols[count - 1].start;
            pending = 0;
        }
        if (type != 't' && type != 'T') continue;
        if (count == capacity) symbols = realloc(symbols, (capacity = capacity ? capacity * 2 : 1024) * sizeof *symbols);
        symbols[count] = (symbol_t){start, size, "", 0, 0};
        snprintf(symbols[count++].name, sizeof symbols->name, "%s", name);
        pending = !size;
    }
    fclose(f);
    uint64_t covered = 0;
    for (size_t i = 0; i < count; i++)
        for (uint32_t a = symbols[i].start; a < symbols[i].start + symbols[i].size && a < RAM_SIZE; a += 4) {
            symbols[i].instret += profile_instret[a / 4];
            symbols[i].cycles += profile_cycles[a / 4];
        }
    for (size_t i = 0; i < count; i++) covered += symbols[i].instret;
    qsort(symbols, count, sizeof *symbols, by_instret);
    FILE *out = open_out(o, "profile.txt");
    fprintf(out, "# cycles%%  instret%%  cycles  instret  function (%.1f%% of instret attributed)\n",
            total_instret ? 100.0 * covered / total_instret : 0);
    for (size_t i = 0; i < count && symbols[i].instret; i++)
        fprintf(out, "%6.2f %6.2f %12" PRIu64 " %12" PRIu64 "  %s\n", 100.0 * symbols[i].cycles / total_cycles,
                100.0 * symbols[i].instret / total_instret, symbols[i].cycles, symbols[i].instret, symbols[i].name);
    fclose(out);
    free(symbols);
}

int main(int argc, char **argv)
{
    options_t o;
    if (parse_options(argc, argv, &o)) return 64;
    ram = calloc(1, RAM_SIZE);
    if (load_machine(ram, &o)) return 66;
    run_log_t log;
    run_log_open(&log, &o);
    keys_t keys;
    keys_load(&keys, o.keys);
    keys_frame(&keys, 0);

    if (o.profile) {
        profile_instret = calloc(RAM_SIZE / 4, sizeof *profile_instret);
        profile_cycles = calloc(RAM_SIZE / 4, sizeof *profile_cycles);
    }
    uint64_t limit = o.max_instret ? o.max_instret : UINT64_MAX;
    uint32_t frames = 0;
    int exit_code = -1, cause = 0;
    clock_t started = clock();

    while (instret < limit) {
        if (pc & 3 || pc >= RAM_SIZE) { cause = fault(FAULT_FETCH, 0); break; }
        uint32_t insn = load32(pc);
        uint32_t opcode = insn & 0x7f, rd = (insn >> 7) & 31, f3 = (insn >> 12) & 7;
        uint32_t f7 = insn >> 25;
        uint32_t a = x[(insn >> 15) & 31], b = x[(insn >> 20) & 31];
        int32_t imm_i = (int32_t)insn >> 20;
        int32_t imm_s = ((int32_t)insn >> 25 << 5) | ((insn >> 7) & 31);
        int32_t imm_b = ((int32_t)insn >> 31 << 12) | ((insn & 0x80) << 4) |
                        ((insn >> 20) & 0x7e0) | ((insn >> 7) & 0x1e);
        int32_t imm_j = ((int32_t)insn >> 31 << 20) | (insn & 0xff000) |
                        ((insn >> 9) & 0x800) | ((insn >> 20) & 0x7fe);
        uint32_t next = pc + 4, value = 0;
        int write = 0, illegal = 0, memory = 0;

        switch (opcode) {
        case 0x37: value = insn & 0xfffff000; write = 1; break;
        case 0x17: value = pc + (insn & 0xfffff000); write = 1; break;
        case 0x6f: value = pc + 4; next = pc + imm_j; write = 1; break;
        case 0x67: value = pc + 4; next = (a + imm_i) & ~1u; write = 1; illegal = f3 != 0; break;
        case 0x63: {
            int take = 0;
            switch (f3) {
            case 0: take = a == b; break;
            case 1: take = a != b; break;
            case 4: take = (int32_t)a < (int32_t)b; break;
            case 5: take = (int32_t)a >= (int32_t)b; break;
            case 6: take = a < b; break;
            case 7: take = a >= b; break;
            default: illegal = 1;
            }
            if (take) next = pc + imm_b;
            break;
        }
        case 0x33:
            if (f7 == 1) { /* RV32M */
                int32_t sa = (int32_t)a, sb = (int32_t)b;
                write = 1;
                switch (f3) {
                case 0: value = a * b; break;
                case 1: value = (uint32_t)(((int64_t)sa * sb) >> 32); break;
                case 2: value = (uint32_t)(((int64_t)sa * (int64_t)(uint64_t)b) >> 32); break;
                case 3: value = (uint32_t)(((uint64_t)a * b) >> 32); break;
                case 4: value = !b ? ~0u : (sa == INT32_MIN && sb == -1) ? a : (uint32_t)(sa / sb); break;
                case 5: value = !b ? ~0u : a / b; break;
                case 6: value = !b ? a : (sa == INT32_MIN && sb == -1) ? 0 : (uint32_t)(sa % sb); break;
                case 7: value = !b ? a : a % b; break;
                }
                break;
            }
            /* fall through */
        case 0x13: {
            uint32_t operand = opcode == 0x13 ? (uint32_t)imm_i : b;
            int alternate = (insn >> 30) & 1 && (opcode == 0x33 || f3 == 5);
            write = 1;
            if (opcode == 0x13) {
                if (f3 == 1) illegal = f7 != 0;
                if (f3 == 5) illegal = f7 != 0 && f7 != 0x20;
            } else {
                illegal = f7 != 0 && !(f7 == 0x20 && (f3 == 0 || f3 == 5));
            }
            switch (f3) {
            case 0: value = alternate ? a - operand : a + operand; break;
            case 1: value = a << (operand & 31); break;
            case 2: value = (int32_t)a < (int32_t)operand; break;
            case 3: value = a < operand; break;
            case 4: value = a ^ operand; break;
            case 5: value = alternate ? (uint32_t)((int32_t)a >> (operand & 31)) : a >> (operand & 31); break;
            case 6: value = a | operand; break;
            case 7: value = a & operand; break;
            }
            break;
        }
        case 0x03: case 0x23: {
            int store = opcode == 0x23;
            uint32_t address = a + (store ? imm_s : imm_i);
            /* Fault priority matches the RTL: bus range/MMIO, then alignment, then encoding. */
            int in_mmio = address >= MMIO_BASE && address < MMIO_BASE + MMIO_SIZE;
            if (in_mmio ? f3 != 2 || address - MMIO_BASE == 0x14 : address < NULL_GUARD || address >= RAM_SIZE) {
                cause = fault(in_mmio ? FAULT_MMIO : FAULT_ACCESS, insn);
                goto stop;
            }
            if (((f3 & 3) == 1 && address & 1) || ((f3 & 3) == 2 && address & 3)) {
                cause = fault(FAULT_ALIGN, insn);
                goto stop;
            }
            if (store ? f3 > 2 : !(f3 == 0 || f3 == 1 || f3 == 2 || f3 == 4 || f3 == 5)) { illegal = 1; break; }
            memory = 1;
            if (in_mmio) {
                uint32_t offset = address - MMIO_BASE;
                uint64_t now = cycles + 2;
                if (store) {
                    if (offset == MMIO_CONSOLE) run_log_console(&log, (char)b);
                    else if (offset == MMIO_EXIT) { exit_code = (int)b; instret++; cycles += 3; pc += 4; goto stop; }
                    else if (offset == MMIO_FRAME) {
                        frames++;
                        run_log_frame(&log, frames, b, instret + 1, now + 1, ram);
                        keys_frame(&keys, frames);
                        if (o.max_frames && frames >= o.max_frames) { instret++; cycles += 3; pc += 4; goto stop; }
                    } else if (offset == MMIO_KEY_ACK) keys_pop(&keys);
                } else {
                    switch (offset) {
                    case MMIO_KEY: value = keys_peek(&keys); break;
                    case MMIO_CYCLE_LO: value = (uint32_t)now; break;
                    case MMIO_CYCLE_HI: value = (uint32_t)(now >> 32); break;
                    case MMIO_INSTRET_LO: value = (uint32_t)instret; break;
                    case MMIO_INSTRET_HI: value = (uint32_t)(instret >> 32); break;
                    default: value = 0;
                    }
                }
            } else if (store) {
                if (f3 == 0) ram[address] = (uint8_t)b;
                else if (f3 == 1) memcpy(ram + address, &b, 2);
                else memcpy(ram + address, &b, 4);
                run_log_store(&log, address);
            } else {
                switch (f3) {
                case 0: value = (uint32_t)(int8_t)ram[address]; break;
                case 1: { int16_t h; memcpy(&h, ram + address, 2); value = (uint32_t)h; break; }
                case 2: value = load32(address); break;
                case 4: value = ram[address]; break;
                case 5: { uint16_t h; memcpy(&h, ram + address, 2); value = h; break; }
                }
            }
            write = !store;
            break;
        }
        case 0x0f: illegal = f3 != 0; break;
        default: illegal = 1;
        }
        if (next & 3) illegal = 1;
        if (illegal) { cause = fault(FAULT_ILLEGAL, insn); break; }
        if (write && rd) x[rd] = value;
        run_log_retire(&log, instret, pc, insn, write && rd ? rd : 0, value, x[2]);
        if (profile_instret) {
            profile_instret[pc / 4]++;
            profile_cycles[pc / 4] += memory ? 3 : 2;
        }
        pc = next;
        instret++;
        cycles += memory ? 3 : 2;
    }
stop:;
    double seconds = (double)(clock() - started) / CLOCKS_PER_SEC;
    if (o.profile) write_profile(&o, instret, cycles);
    run_log_close(&log, exit_code, cause, pc, instret, cycles, frames, seconds);
    return cause ? 2 : exit_code == 0 || exit_code == -1 ? 0 : 1;
}
