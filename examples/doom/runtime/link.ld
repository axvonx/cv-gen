ENTRY(_start)
SECTIONS {
 . = 0;
 .start : { KEEP(*(.text.start)) }
 . = 0x1000;
 .text : { *(.text*) }
 .rodata : ALIGN(16) { *(.rodata*) *(.srodata*) }
 .data : ALIGN(16) { *(.data*) *(.sdata*) }
 .bss (NOLOAD) : ALIGN(16) { __bss_start = .; *(.bss*) *(.sbss*) *(COMMON) . = ALIGN(16); __bss_end = .; }
 _end = .;
 /DISCARD/ : { *(.comment) *(.riscv.attributes) *(.eh_frame*) }
}
ASSERT(SIZEOF(.start) <= 0x1000, "startup code must fit in page 0")
ASSERT(_end <= 0x00a00000, "image overlaps the heap limit")
