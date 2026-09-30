// Shared-address asynchronous RAM matches CircuitVerse's native RAM primitive.
// CPU wrappers enable writes only during the low half of a clock cycle.
module async_ram #(parameter DATA=8, parameter ADDR=12) (
    input [ADDR-1:0] address, input [DATA-1:0] data,
    input write_enable, output [DATA-1:0] q
);
    (* nomem2reg *) reg [DATA-1:0] cells[0:(1<<ADDR)-1];
    integer i;
    generate if(ADDR==16)begin
        initial $readmemh("examples/common/zero.hex",cells);
    end else begin
        initial for(i=0;i<(1<<ADDR);i=i+1) cells[i]=0;
    end endgenerate
    always @* if(write_enable) cells[address] <= data;
    assign q=cells[address];
endmodule
