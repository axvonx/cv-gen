// Four independent byte RAMs provide native whole-byte writes without masked RAM.
module rv32_lanes(input [1:0] offset,input [2:0] size,
 input [31:0] word,data,output reg [31:0] loaded,
 output [31:0] shifted,output reg [3:0] mask);
 wire [31:0] selected=word>>{offset,3'b0};
 assign shifted=data<<{offset,3'b0};
 always @* begin
  case(size)
   0:loaded={{24{selected[7]}},selected[7:0]};
   1:loaded={{16{selected[15]}},selected[15:0]};
   2:loaded=selected;
   4:loaded={24'b0,selected[7:0]};
   5:loaded={16'b0,selected[15:0]};
   default:loaded=0;
  endcase
  case(size)
   0:mask=4'b0001<<offset;
   1:mask=4'b0011<<offset;
   2:mask=4'b1111;
   default:mask=0;
  endcase
 end
endmodule
