// Double-dabble conversion avoids division hardware and keeps this scope small.
module chip8_bcd(input [7:0] value,output [7:0] hundreds,tens,ones);
 reg [11:0] digits;integer i;
 always @* begin
  digits=0;
  for(i=7;i>=0;i=i-1)begin
   if(digits[3:0]>=5)digits[3:0]=digits[3:0]+4'd3;
   if(digits[7:4]>=5)digits[7:4]=digits[7:4]+4'd3;
   if(digits[11:8]>=5)digits[11:8]=digits[11:8]+4'd3;
   digits={digits[10:0],value[i]};
  end
 end
 assign hundreds={4'b0,digits[11:8]};
 assign tens={4'b0,digits[7:4]};assign ones={4'b0,digits[3:0]};
endmodule
