// One shared RAM address per byte lane: loader, paused inspection, or CPU.
module rv32_memory(input clk,rst,load_enable,inspect,
 input [15:0] load_address,peek_address,input [31:0] load_data,
 input [31:0] address,data,input [2:0] size,input write,
 output [31:0] word,output [7:0] pixel,
 output [7:0] screen_address,output [31:0] screen_data,
 output [3:0] screen_mask,output screen_write);
 wire [15:0] selected=load_enable ? load_address : inspect ? peek_address : address[15:0];
 wire [31:0] shifted,unused;
 wire [3:0] mask;
 rv32_lanes lanes(address[1:0],size,32'b0,data,unused,shifted,mask);
 wire [31:0] writing=load_enable ? load_data : shifted;
 wire cpu_write=write && address>=32'h4000 && address<32'h10000 && !inspect;
 wire enable=!clk && !rst && (load_enable || cpu_write);
 // Native screen observes exactly the writes accepted by the RAM lanes.
 assign screen_address=selected[7:0];
 assign screen_data=writing;
 assign screen_mask=load_enable ? 4'b1111 : mask;
 assign screen_write=enable && selected[15:8]==8'hf0;
 genvar g;
 generate for(g=0;g<4;g=g+1)begin:lane
  async_ram #(.DATA(8),.ADDR(14)) memory(selected[15:2],writing[g*8+:8],enable && (load_enable || mask[g]),word[g*8+:8]);
 end endgenerate
 assign pixel=selected[1] ? (selected[0] ? word[31:24] : word[23:16]) :
                                (selected[0] ? word[15:8] : word[7:0]);
endmodule
