/** Native RAM mapping for a single shared-address, asynchronous memory port.
 * CircuitVerse RAM writes while enabled. Clocked and masked memories must not
 * silently use it; this mapper rejects those shapes.
 */
function install(types, RAM, Multiplexer, ConstantVal, Rom, Splitter) {
  types.Memory = class {
    constructor(dev) {
      if(dev.wrports.length===0 && dev.rdports.length===1 && dev.bits<=8 && dev.abits>=1 && dev.abits<=4 && dev.words<=16 && !dev.offset && dev.rdports[0].clock_polarity===undefined){
        const data=[];
        for(let i=0;i<dev.memdata.length;i++){
          const count=typeof dev.memdata[i]==='number'?dev.memdata[i++]:1;
          const value=parseInt(dev.memdata[i].replaceAll('x','0'),2);
          for(let j=0;j<count;j++)data.push(value);
        }
        while(data.length<16)data.push(0);
        const rom=new Rom(0,0,undefined,data);rom.label=dev.label;
        new ConstantVal(0,0,undefined,undefined,1,'1').output1.connect(rom.en);
        let address=rom.memAddr,output=rom.dataOut;
        if(dev.abits<4){
          const bridge=new Splitter(0,0,undefined,undefined,4,[dev.abits,4-dev.abits]);
          bridge.inp1.connect(rom.memAddr);
          new ConstantVal(0,0,undefined,undefined,4-dev.abits,'0'.repeat(4-dev.abits)).output1.connect(bridge.outputs[1]);
          address=bridge.outputs[0];
        }
        if(dev.bits<8){
          const bridge=new Splitter(0,0,undefined,undefined,8,[dev.bits,8-dev.bits]);
          rom.dataOut.connect(bridge.inp1);output=bridge.outputs[0];
        }
        this.ports={rd0addr:address,rd0data:output};return;
      }
      if(dev.rdports.length!==1 || dev.wrports.length!==1 ||
         dev.rdports[0].clock_polarity!==undefined || dev.wrports[0].clock_polarity!==undefined ||
         !dev.cvgenSharedAddress || !dev.wrports[0].no_bit_enable) {
        throw Error(`memory ${dev.label}: requires one shared-address asynchronous read/write port with whole-word enable`);
      }
      if(dev.offset || dev.memdata.some(value=>typeof value==='string' && /1/.test(value))) {
        throw Error(`memory ${dev.label}: native RAM requires zero initialization and zero address offset`);
      }
      const ram=new RAM(0,0,undefined,undefined,dev.bits,dev.abits);
      ram.label=dev.label;
      const mux=new Multiplexer(0,0,undefined,undefined,dev.abits,1);
      mux.output1.connect(ram.address);
      mux.controlSignalInput.connect(ram.write);
      const zero=new ConstantVal(0,0,undefined,undefined,1,'0');
      zero.output1.connect(ram.reset);zero.output1.connect(ram.coreDump);
      this.ports={rd0addr:mux.inp[0],wr0addr:mux.inp[1],wr0data:ram.dataIn,wr0en:ram.write,rd0data:ram.dataOut};
    }
    getPort(name){return this.ports[name];}
  };
}
module.exports={install};
