// The DOOM machine: the unchanged RV32I teaching core on the DOOM bus. With run
// low, the host loads the program and WAD through the loader port (present
// address and data, then pulse load_enable); it then runs, acknowledges frame
// doorbells (the CPU halts while frame_pending) and pushes key events.
module rv32_doom(input clk,rst,run,load_enable,inspect,
 input [23:0] load_address,peek_address,input [31:0] load_data,
 input frame_ack,key_push,input [8:0] key_data,
 output [31:0] pc,instruction,a0,sp,peek_word,exit_code,frame_info,
 output [1:0] state,output done,fault,frame_pending,key_full,
 output [2:0] fault_cause,output console_write,output [7:0] console_data,
 output [31:0] cycle_lo,cycle_hi,instret_lo,instret_hi);
 wire [31:0] address,data,memory_q,access_address;
 wire [1:0] access_kind;
 wire [2:0] size;
 wire [15:0] retired;
 wire write,bus_fault;
 wire cpu_run=run && !done && !frame_pending && !load_enable && !inspect;
 rv32_core cpu(clk,rst,cpu_run,bus_fault,memory_q,address,data,write,size,pc,instruction,
               a0,sp,state,retired,fault,access_address,access_kind);
 rv32_doom_bus bus(clk,rst,run,load_enable,inspect,load_address,peek_address,load_data,
                   state,access_kind,pc,address,data,access_address,write,size,retired,
                   cpu_run && !fault,fault,frame_ack,key_push,key_data,memory_q,peek_word,
                   bus_fault,done,frame_pending,exit_code,frame_info,fault_cause,
                   console_write,console_data,key_full,cycle_lo,cycle_hi,instret_lo,instret_hi);
endmodule
