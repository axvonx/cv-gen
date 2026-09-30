ENTRY(_start)
MEMORY {
 ROM (rx) : ORIGIN = 0, LENGTH = 2K
 RAM (rw) : ORIGIN = 0x800, LENGTH = 2K
}
SECTIONS {
 .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) } > ROM
 .data : ALIGN(4) {
  __data_start = .; *(.data*) *(.sdata*) __data_end = .;
 } > RAM AT> ROM
 __data_load = LOADADDR(.data);
 .bss (NOLOAD) : ALIGN(4) {
  __bss_start = .; *(.bss*) *(.sbss*) *(COMMON) __bss_end = .;
 } > RAM
 /DISCARD/ : { *(.comment) *(.riscv.attributes) *(.eh_frame*) }
}
ASSERT(__bss_end <= 0xf00, "reserve at least 256 bytes for the stack")
