; Readable listing of the ROM demo. Main entry is x3000.
.ORIG x3000
    AND R0, R0, #0
    ADD R0, R0, #3
    ADD R1, R0, #5
    ST  R1, SAVED
    LD  R2, SAVED
    NOT R3, R2
    ADD R3, R3, #1
    BRn CALL
    ADD R2, R2, #1 ; skipped
CALL JSR INC
    TRAP x25
    BRnzp #-1
INC ADD R2, R2, #1
    RET
    .BLKW 2
SAVED .FILL 0 ; x3010, RAM, outside the ROM overlay
.END
; Vector x0025 contains x3100.
; HALT handler at x3100:
; AND R0,R0,#0 / STI R0,#1 / RET / .FILL xFFFE
