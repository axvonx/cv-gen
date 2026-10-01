/* Memory map and MMIO ABI of the DOOM machine, shared by the runtime, the ISS
   oracle and the Verilator testbench. The RTL in examples/doom mirrors it. */
#ifndef DOOM_MACHINE_H
#define DOOM_MACHINE_H

#define RAM_SIZE        0x01000000u /* 16 MiB: 4 banks x 4 byte lanes x 2^20 */
#define NULL_GUARD      0x00001000u /* data accesses below this address fault */
#define HEAP_LIMIT      0x00a00000u
#define STACK_TOP       0x00b00000u
#define WAD_HEADER      0x00b00000u /* {WAD_MAGIC, byte length} then the file */
#define WAD_DATA        0x00b00010u
#define WAD_MAGIC       0x21444157u /* "WAD!" */
#define FRAMEBUFFER     0x00f10000u /* 320x200 palette indices */
#define PALETTE         0x00f20000u /* 256 x {r,g,b} bytes */
#define SCREEN_WIDTH    320
#define SCREEN_HEIGHT   200

#define MMIO_BASE       0x10000000u /* word accesses only */
#define MMIO_CONSOLE    0x00u /* W: low byte to console */
#define MMIO_EXIT       0x04u /* W: exit code; machine halts (done) */
#define MMIO_FRAME      0x08u /* W: frame doorbell, value = frame info */
#define MMIO_KEY        0x0cu /* R: bit 8 valid, bit 9 pressed, bits 7:0 key */
#define MMIO_KEY_ACK    0x10u /* W: pop the key mailbox */
#define MMIO_CYCLE_LO   0x18u /* R: clock cycles since reset (64-bit) */
#define MMIO_CYCLE_HI   0x1cu
#define MMIO_INSTRET_LO 0x20u /* R: retired instructions since reset (64-bit) */
#define MMIO_INSTRET_HI 0x24u
#define MMIO_SIZE       0x28u

/* Frame doorbell value: gamestate in bits 31:28, wiping in bit 27,
   gametic in bits 26:0. */
#define FRAME_INFO(state, wiping, tic) \
    (((unsigned)(state) << 28) | ((unsigned)(wiping) << 27) | ((unsigned)(tic) & 0x07ffffffu))

/* Fault causes reported by the RTL and the ISS. */
#define FAULT_NONE     0
#define FAULT_ILLEGAL  1 /* illegal or unsupported instruction */
#define FAULT_FETCH    2 /* misaligned pc or pc outside RAM */
#define FAULT_ALIGN    3 /* misaligned load/store */
#define FAULT_ACCESS   4 /* load/store outside RAM/MMIO or in the null guard */
#define FAULT_MMIO     5 /* non-word or undefined MMIO access */

#endif
