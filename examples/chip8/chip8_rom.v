module chip8_rom_bank_0(input [3:0] address,output [7:0] data);
 reg [7:0] cells[0:15];
 initial begin
 cells[0]=8'hf0;
 cells[1]=8'h90;
 cells[2]=8'h90;
 cells[3]=8'h90;
 cells[4]=8'hf0;
 cells[5]=8'h20;
 cells[6]=8'h60;
 cells[7]=8'h20;
 cells[8]=8'h20;
 cells[9]=8'h70;
 cells[10]=8'hf0;
 cells[11]=8'h10;
 cells[12]=8'hf0;
 cells[13]=8'h80;
 cells[14]=8'hf0;
 cells[15]=8'hf0;
 end
 assign data=cells[address];
endmodule
module chip8_rom_bank_1(input [3:0] address,output [7:0] data);
 reg [7:0] cells[0:15];
 initial begin
 cells[0]=8'h10;
 cells[1]=8'hf0;
 cells[2]=8'h10;
 cells[3]=8'hf0;
 cells[4]=8'h90;
 cells[5]=8'h90;
 cells[6]=8'hf0;
 cells[7]=8'h10;
 cells[8]=8'h10;
 cells[9]=8'hf0;
 cells[10]=8'h80;
 cells[11]=8'hf0;
 cells[12]=8'h10;
 cells[13]=8'hf0;
 cells[14]=8'hf0;
 cells[15]=8'h80;
 end
 assign data=cells[address];
endmodule
module chip8_rom_bank_2(input [3:0] address,output [7:0] data);
 reg [7:0] cells[0:15];
 initial begin
 cells[0]=8'hf0;
 cells[1]=8'h90;
 cells[2]=8'hf0;
 cells[3]=8'hf0;
 cells[4]=8'h10;
 cells[5]=8'h20;
 cells[6]=8'h40;
 cells[7]=8'h40;
 cells[8]=8'hf0;
 cells[9]=8'h90;
 cells[10]=8'hf0;
 cells[11]=8'h90;
 cells[12]=8'hf0;
 cells[13]=8'hf0;
 cells[14]=8'h90;
 cells[15]=8'hf0;
 end
 assign data=cells[address];
endmodule
module chip8_rom_bank_3(input [3:0] address,output [7:0] data);
 reg [7:0] cells[0:15];
 initial begin
 cells[0]=8'h10;
 cells[1]=8'hf0;
 cells[2]=8'hf0;
 cells[3]=8'h90;
 cells[4]=8'hf0;
 cells[5]=8'h90;
 cells[6]=8'h90;
 cells[7]=8'he0;
 cells[8]=8'h90;
 cells[9]=8'he0;
 cells[10]=8'h90;
 cells[11]=8'he0;
 cells[12]=8'hf0;
 cells[13]=8'h80;
 cells[14]=8'h80;
 cells[15]=8'h80;
 end
 assign data=cells[address];
endmodule
module chip8_rom_bank_4(input [3:0] address,output [7:0] data);
 reg [7:0] cells[0:15];
 initial begin
 cells[0]=8'hf0;
 cells[1]=8'he0;
 cells[2]=8'h90;
 cells[3]=8'h90;
 cells[4]=8'h90;
 cells[5]=8'he0;
 cells[6]=8'hf0;
 cells[7]=8'h80;
 cells[8]=8'hf0;
 cells[9]=8'h80;
 cells[10]=8'hf0;
 cells[11]=8'hf0;
 cells[12]=8'h80;
 cells[13]=8'hf0;
 cells[14]=8'h80;
 cells[15]=8'h80;
 end
 assign data=cells[address];
endmodule
module chip8_rom_bank_20(input [3:0] address,output [7:0] data);
 reg [7:0] cells[0:15];
 initial begin
 cells[0]=8'h60;
 cells[1]=8'h03;
 cells[2]=8'h61;
 cells[3]=8'h05;
 cells[4]=8'h80;
 cells[5]=8'h14;
 cells[6]=8'ha3;
 cells[7]=8'h00;
 cells[8]=8'hf1;
 cells[9]=8'h55;
 cells[10]=8'ha3;
 cells[11]=8'h00;
 cells[12]=8'h60;
 cells[13]=8'h00;
 cells[14]=8'hf0;
 cells[15]=8'h65;
 end
 assign data=cells[address];
endmodule
module chip8_rom_bank_21(input [3:0] address,output [7:0] data);
 reg [7:0] cells[0:15];
 initial begin
 cells[0]=8'h62;
 cells[1]=8'h01;
 cells[2]=8'h63;
 cells[3]=8'h02;
 cells[4]=8'ha3;
 cells[5]=8'h20;
 cells[6]=8'hd2;
 cells[7]=8'h31;
 cells[8]=8'hd2;
 cells[9]=8'h31;
 cells[10]=8'h22;
 cells[11]=8'h22;
 cells[12]=8'h30;
 cells[13]=8'h10;
 cells[14]=8'h60;
 cells[15]=8'h00;
 end
 assign data=cells[address];
endmodule
module chip8_rom_bank_22(input [3:0] address,output [7:0] data);
 reg [7:0] cells[0:15];
 initial begin
 cells[0]=8'h12;
 cells[1]=8'h20;
 cells[2]=8'h70;
 cells[3]=8'h08;
 cells[4]=8'h00;
 cells[5]=8'hee;
 cells[6]=8'h00;
 cells[7]=8'h00;
 cells[8]=8'h00;
 cells[9]=8'h00;
 cells[10]=8'h00;
 cells[11]=8'h00;
 cells[12]=8'h00;
 cells[13]=8'h00;
 cells[14]=8'h00;
 cells[15]=8'h00;
 end
 assign data=cells[address];
endmodule
module chip8_rom(input [11:0] address,output reg [7:0] data,output reg valid);
 wire [7:0] bank_0;
 chip8_rom_bank_0 rom_0(address[3:0],bank_0);
 wire [7:0] bank_1;
 chip8_rom_bank_1 rom_1(address[3:0],bank_1);
 wire [7:0] bank_2;
 chip8_rom_bank_2 rom_2(address[3:0],bank_2);
 wire [7:0] bank_3;
 chip8_rom_bank_3 rom_3(address[3:0],bank_3);
 wire [7:0] bank_4;
 chip8_rom_bank_4 rom_4(address[3:0],bank_4);
 wire [7:0] bank_20;
 chip8_rom_bank_20 rom_20(address[3:0],bank_20);
 wire [7:0] bank_21;
 chip8_rom_bank_21 rom_21(address[3:0],bank_21);
 wire [7:0] bank_22;
 chip8_rom_bank_22 rom_22(address[3:0],bank_22);
 always @* begin data=0;valid=1;case(address[11:4])
 8'h00:data=bank_0;
 8'h01:data=bank_1;
 8'h02:data=bank_2;
 8'h03:data=bank_3;
 8'h04:data=bank_4;
 8'h20:data=bank_20;
 8'h21:data=bank_21;
 8'h22:data=bank_22;
 8'h32:begin data=8'h80;valid=address[3:0]==0;end
 default:valid=0;endcase end
endmodule
