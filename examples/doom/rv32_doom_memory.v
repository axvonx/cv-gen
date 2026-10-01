// 16 MiB as 4 banks x 4 byte lanes of 2^20-entry RAMs, CircuitVerse's largest RAM.
// One shared address per RAM: inspection, the loader (while not running), or CPU.
//
// The port muxes select on inspect/run, never on load_enable: load_enable only
// gates the write. The host presents load_address/load_data, then pulses
// load_enable. In CircuitVerse's event-driven simulation a mux switched by the
// falling enable could change the RAM data a gate earlier than the enable falls
// and overwrite the word just loaded.
module rv32_doom_memory(input clk,rst,run,load_enable,inspect,
 input [23:0] load_address,peek_address,input [31:0] load_data,
 input [31:0] address,data,input [2:0] size,input write,
 output [31:0] word);
 wire loader=!run;
 wire [23:0] selected=inspect ? peek_address : loader ? load_address : address[23:0];
 wire [31:0] shifted,unused;
 wire [3:0] mask;
 rv32_lanes lanes(address[1:0],size,32'b0,data,unused,shifted,mask);
 wire [31:0] writing=loader ? load_data : shifted;
 wire cpu_write=write && address<32'h1000000 && !inspect;
 wire enable=!clk && !rst && (loader ? load_enable && !inspect : cpu_write);
 wire [3:0] lane_write=loader ? 4'b1111 : mask;
 wire [1:0] bank=selected[23:22];
 wire [31:0] q0,q1,q2,q3;
 genvar g;
 generate for(g=0;g<4;g=g+1)begin:lane
  async_ram #(.DATA(8),.ADDR(20),.INIT(0)) b0(selected[21:2],writing[g*8+:8],enable && lane_write[g] && bank==0,q0[g*8+:8]);
  async_ram #(.DATA(8),.ADDR(20),.INIT(0)) b1(selected[21:2],writing[g*8+:8],enable && lane_write[g] && bank==1,q1[g*8+:8]);
  async_ram #(.DATA(8),.ADDR(20),.INIT(0)) b2(selected[21:2],writing[g*8+:8],enable && lane_write[g] && bank==2,q2[g*8+:8]);
  async_ram #(.DATA(8),.ADDR(20),.INIT(0)) b3(selected[21:2],writing[g*8+:8],enable && lane_write[g] && bank==3,q3[g*8+:8]);
 end endgenerate
 assign word=bank[1] ? (bank[0] ? q3 : q2) : (bank[0] ? q1 : q0);
endmodule
