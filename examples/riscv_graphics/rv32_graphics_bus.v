module rv32_graphics_bus(input clk,rst,boot_ram,load_enable,inspect,
 input [15:0] load_address,peek_address,input [31:0] load_data,
 input [1:0] state,access_kind,input [31:0] pc,address,data,access_address,
 input write,input [2:0] size,output [31:0] memory_q,peek_word,result,
 output [7:0] pixel,output done,bus_fault,
 output [7:0] screen_address,output [31:0] screen_data,
 output [3:0] screen_mask,output screen_write);
 wire [31:0] rom_q;
 reg [31:0] result_register;
 reg done_register;
 wire legal_mmio=access_address==32'h10000 || access_address==32'h10004;
 assign bus_fault=state==1 && access_kind!=0 ?
   ((access_address>=32'h10000 && !(legal_mmio && size==2)) ||
    (access_kind[1] && access_address<32'h4000)) :
   (state==0 && (pc>=32'h10000 || pc[1:0]!=0));
 rv32_graphics_rom program_rom(address[13:2],rom_q);
 rv32_memory memory(clk,rst,load_enable,inspect,load_address,peek_address,load_data,
                    address,data,size,write,peek_word,pixel,
                    screen_address,screen_data,screen_mask,screen_write);
 always @(posedge clk or posedge rst)
  if(rst)begin result_register<=0;done_register<=0;end
  else if(write && !bus_fault && !load_enable && !inspect)begin
   if(address==32'h10000)result_register<=data;
   if(address==32'h10004 && data!=0)done_register<=1;
  end
 assign result=result_register;
 assign done=done_register;
 // JAL x0,0x4000 selects the RAM image without changing the CPU implementation.
 assign memory_q=address==32'h10000 ? result_register :
                 address==32'h10004 ? {31'b0,done_register} :
                 address<32'h4000 ? (boot_ram && address==0 ? 32'h0000406f : rom_q) : peek_word;
endmodule
