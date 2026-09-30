; Readable CHIP-8 instruction listing, starting at byte address 0x200.
LD V0, 3
LD V1, 5
ADD V0, V1
LD I, 0x300
STORE V0..V1
LD I, 0x300
LD V0, 0
LOAD V0
LD V2, 1
LD V3, 2
LD I, 0x320 ; one sprite byte 0x80
DRAW V2, V3, 1
DRAW V2, V3, 1
CALL 0x222
SE V0, 16
LD V0, 0 ; skipped
JP 0x220
ADD V0, 8 ; subroutine at 0x222
RET
