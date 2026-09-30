// Focused machine view: CPU plus memory/peripheral bus, all gates in child scopes.
module rv32_demo(input clk,rst,run,
 output [31:0] pc,instruction,a0,sp,result,
 output [15:0] retired,output [1:0] state,output done,fault,output [31:0] bus_address);
 wire [31:0] address,data,memory_q,access_address;
 wire [1:0] access_kind;
 wire [2:0] size;
 wire write,bus_fault;
 rv32_core cpu(clk,rst,run && !done,bus_fault,memory_q,address,data,write,size,
               pc,instruction,a0,sp,state,retired,fault,access_address,access_kind);
 rv32_bus memory_and_peripherals(clk,rst,state,pc,address,data,access_address,
                                access_kind,write,size,memory_q,result,done,bus_fault);
 assign bus_address=address;
endmodule
