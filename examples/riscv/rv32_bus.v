module rv32_bus(input clk,rst,input [1:0] state,input [31:0] pc,
 input [31:0] address,data,access_address,input [1:0] access_kind,
 input write,input [2:0] size,
 output [31:0] memory_q,result,output done,bus_fault);
 wire [31:0] ram_q,rom_q,shifted;
 wire [3:0] mask;
 wire [31:0] unused_loaded;
 reg [31:0] result_register;
 reg done_register;
 wire in_ram=access_address<32'h1000;
 wire mmio=access_address==32'h1000 || access_address==32'h1004;
 // Validate stable decoded addresses in EXECUTE, before switching the bus.
 assign bus_fault=state==1 && access_kind!=0 ?
   ((!in_ram && !(mmio && size==2)) || (access_kind[1] && access_address<32'h800)) :
   (state==0 && (pc>=32'h1000 || pc[1:0]!=0));
 rv32_rom program_rom(address[10:2],rom_q);
 rv32_lanes lanes(address[1:0],size,32'b0,data,unused_loaded,shifted,mask);
 wire ram_write=!clk && !rst && write && in_ram && !bus_fault;
 genvar g;
 generate for(g=0;g<4;g=g+1)begin:byte_lane
  async_ram #(.DATA(8),.ADDR(10)) memory(address[11:2],shifted[g*8+:8],ram_write && mask[g],ram_q[g*8+:8]);
 end endgenerate
 // MMIO commits on the rising edge at the end of the low-phase store.
 always @(posedge clk or posedge rst)
  if(rst)begin result_register<=0;done_register<=0;end
  else if(write && !bus_fault)begin
   if(address==32'h1000)result_register<=data;
   if(address==32'h1004 && data!=0)done_register<=1;
  end
 assign result=result_register;
 assign done=done_register;
 assign memory_q=address==32'h1000 ? result_register : address==32'h1004 ? {31'b0,done_register} : address<32'h800 ? rom_q : ram_q;
endmodule
