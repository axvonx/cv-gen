module rv32_graphics(input clk,rst,run,boot_ram,load_enable,inspect,
 input [15:0] load_address,peek_address,input [31:0] load_data,
 output [31:0] pc,instruction,a0,sp,result,peek_word,
 output [15:0] retired,output [1:0] state,output [7:0] pixel,output done,fault,
 output [7:0] screen_address,output [31:0] screen_data,
 output [3:0] screen_mask,output screen_write);
 wire [31:0] address,data,memory_q,access_address;
 wire [1:0] access_kind;
 wire [2:0] size;
 wire write,bus_fault;
 rv32_core cpu(clk,rst,run && !done && !load_enable && !inspect,bus_fault,
               memory_q,address,data,write,size,pc,instruction,a0,sp,state,retired,
               fault,access_address,access_kind);
 rv32_graphics_bus bus(clk,rst,boot_ram,load_enable,inspect,load_address,peek_address,
                       load_data,state,access_kind,pc,address,data,access_address,
                       write,size,memory_q,peek_word,result,pixel,done,bus_fault,
                       screen_address,screen_data,screen_mask,screen_write);
endmodule
