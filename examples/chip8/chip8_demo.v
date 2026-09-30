module chip8_demo(input clk,rst,run,timer_tick,input [15:0] keys,
 input [7:0] random_byte,input [10:0] view_address,
 input load_enable,input [11:0] load_address,input [7:0] load_data,input demo_enable,
 output [11:0] pc,index_reg,output [15:0] instruction,
 output [7:0] v0,vf,delay_timer,sound_timer,retired,
 output [4:0] state,output fault,done,view_pixel);
 wire [11:0] memory_address;wire [7:0] memory_data,memory_q,ram_q,rom_q;
 wire memory_write,rom_valid;
 wire [10:0] pixel_address;wire pixel_write,pixel_data,pixel_q;
 chip8_core cpu(clk,rst,run && !load_enable,timer_tick,keys,random_byte,
  memory_address,memory_data,memory_write,memory_q,pixel_address,pixel_write,pixel_data,pixel_q,
  pc,index_reg,instruction,v0,vf,delay_timer,sound_timer,state,retired,fault);
 wire [11:0] ram_address=load_enable?load_address:memory_address;
 wire [7:0] ram_data=load_enable?load_data:memory_data;
 wire ram_write=!clk && !rst && (load_enable || memory_write);
 async_ram #(.DATA(8),.ADDR(12)) memory(ram_address,ram_data,ram_write,ram_q);
 chip8_rom rom(memory_address,rom_q,rom_valid);
 assign memory_q=demo_enable && rom_valid?rom_q:ram_q;
 // The display shares its port with the viewer whenever the drawing engine is idle.
 wire drawing=state==7 || state==8 || state==9;
 wire [10:0] display_address=drawing?pixel_address:view_address;
 async_ram #(.DATA(1),.ADDR(11)) display(display_address,{pixel_data},pixel_write && !clk && !rst,pixel_q);
 assign view_pixel=pixel_q;
 assign done=pc==12'h220 && retired>=17 && !fault;
endmodule
