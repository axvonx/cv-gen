// A native CircuitVerse screen: no browser extension or custom element required.
exports.install=function(api,scopes){
 const {newCircuit,switchCircuit,Node,Input,Output,Splitter,Decoder,AndGate,RAM,ConstantVal,route,kinds}=api;
 if(scopes.some(s=>s.name==='Framebuffer driver')){
  for(const scope of scopes)for(const matrix of scope.RGBLedMatrix||[]){
   matrix.colors=Array.from({length:16},(_,r)=>Array.from({length:16},(_,c)=>matrix.colors[r]?.[c]||0));
  }
  return;
 }
 const original=Node.prototype.connect;
 Node.prototype.connect=Node.prototype.connectWireLess;
 const driver=newCircuit('Framebuffer driver');
 const input=(name,width)=>{const p=new Input(0,0,driver,'RIGHT',width);p.label=name;return p.output1;};
 const addr=input('screen_address',8),data=input('screen_data',32),mask=input('screen_mask',4),write=input('screen_write',1);
 const address=new Splitter(0,0,driver,'RIGHT',8,[2,2,4]);addr.connect(address.inp1);
 const bytes=new Splitter(0,0,driver,'RIGHT',32,[8,8,8,8]);data.connect(bytes.inp1);
 const masks=new Splitter(0,0,driver,'RIGHT',4,[1,1,1,1]);mask.connect(masks.inp1);
 const rows=new Decoder(0,0,driver,'RIGHT',4);address.outputs[2].connect(rows.input);
 const words=new Decoder(0,0,driver,'RIGHT',2);address.outputs[1].connect(words.input);
 const zero=new ConstantVal(0,0,driver,'RIGHT',1,'0');
 for(let row=0;row<16;row++){
  const p=new Output(0,0,driver,'LEFT',1);p.label=`row_${row}`;rows.output1[row].connect(p.inp1);
 }
 for(let column=0;column<16;column++){
  // A 16-byte native RAM per column keeps every color signal defined. Reading
  // the selected row repaints all its columns; masked writes change only the
  // accepted byte lanes. No high-impedance buses are needed at the matrix.
  const gate=new AndGate(0,0,driver,'RIGHT',3,1);
  words.output1[column>>2].connect(gate.inp[0]);masks.outputs[column&3].connect(gate.inp[1]);
  write.connect(gate.inp[2]);
  const memory=new RAM(0,0,driver,'RIGHT',8,4);
  address.outputs[2].connect(memory.address);bytes.outputs[column&3].connect(memory.dataIn);
  gate.output1.connect(memory.write);zero.output1.connect(memory.reset);zero.output1.connect(memory.coreDump);
  const rgb=new Splitter(0,0,driver,'RIGHT',24,[8,8,8]);
  for(const pin of rgb.outputs)memory.dataOut.connect(pin);
  const p=new Output(0,0,driver,'LEFT',24);p.label=`color_${column}`;rgb.inp1.connect(p.inp1);
 }
 route(driver,kinds,Node);
 // Restore electrical nets without bends before placing the extended scopes.
 function unroute(scope){
  const seen=new Set(),nets=[];
  for(const pin of scope.allNodes){
   if(seen.has(pin))continue;
   const stack=[pin],net=[];
   while(stack.length){const n=stack.pop();if(seen.has(n))continue;seen.add(n);net.push(n);stack.push(...n.connections);}
   nets.push(net.filter(n=>n.type!==2));
  }
  for(const n of scope.allNodes) n.connections=[];
  scope.wires=[];
  for(const n of scope.allNodes.slice())if(n.type===2)n.delete();
  for(const net of nets)for(const n of net.slice(1))net[0].connect(n);
 }
 for(const scope of scopes.filter(s=>['rv32_graphics','Demo'].includes(s.name))){
  switchCircuit(scope.id);unroute(scope);
  exports.panel(api,scope,driver);
  route(scope,kinds,Node);
 }
 Node.prototype.connect=original;
};

exports.panel=function(api,scope,driver){
 const {SubCircuit,RGBLedMatrix}=api;
 const block=new SubCircuit(0,0,scope,driver.id);block.label='Framebuffer controller';
 for(let i=0;i<driver.Input.length;i++){
  const port=scope.Output.find(p=>p.label===driver.Input[i].label);
  if(!port)throw Error(`missing display bus ${driver.Input[i].label}`);
  port.inp1.connect(block.inputNodes[i]);
 }
 const screen=new RGBLedMatrix(0,0,scope,{rows:16,columns:16,ledSize:2,showGrid:false,
  colors:Array.from({length:16},()=>Array(16).fill(0))});
 screen.label='SCREEN — 16 × 16';
 for(let i=0;i<driver.Output.length;i++){
  const [kind,index]=driver.Output[i].label.split('_');
  block.outputNodes[i].connect(kind==='row'?screen.rowEnableNodes[+index]:screen.columnColorNodes[+index]);
 }
 return screen;
};
exports.testWrites=function(api,scopes){
 const {Input,Output,play,errorDetectedGet,errorDetectedSet}=api;
 const driver=scopes.find(s=>s.name==='Framebuffer driver');
 const fixture=api.newCircuit('Screen regression');
 const controls={};
 for(const [name,width] of [['screen_address',8],['screen_data',32],['screen_mask',4],['screen_write',1]]){
  const input=new Input(0,0,fixture,'RIGHT',width);
  controls[name]=input;
  const output=new Output(0,0,fixture,'LEFT',width);output.label=name;
  input.output1.connect(output.inp1);
 }
 const matrix=exports.panel(api,fixture,driver);
 const expected=Array(256).fill(0);
 function step(values){
  for(const [name,value] of Object.entries(values))controls[name].state=value;
  play(fixture);
  if(errorDetectedGet())throw Error('screen simulation error');
  const pixels=Array.from({length:256},(_,i)=>matrix.colors[i>>4][i&15]||0);
  if(JSON.stringify(pixels)!==JSON.stringify(expected))throw Error('screen changed wrong pixels');
 }
 errorDetectedSet(false);
 step({screen_address:0,screen_data:0,screen_mask:0,screen_write:0});
 function write(address,data,mask){
  step({screen_write:0});step({screen_address:address,screen_data:data,screen_mask:mask});
  for(let lane=0;lane<4;lane++)if(mask&(1<<lane))expected[(address&252)+lane]=((data>>>(lane*8))&255)*0x010101;
  step({screen_write:1});step({screen_write:0});
 }
 write(0,0x11223344,15); // full word, four different grayscale pixels
 write(0,0x0000a500,2); // isolated byte must preserve the other lanes
 write(20,0xbeef0000,12); // halfword on the next row
 write(252,0xdeadbeef,15); // bottom-right edge
 step({screen_address:128,screen_data:0xffffffff,screen_mask:15}); // disabled writes retain pixels
 delete api.scopeList[fixture.id];
 api.switchCircuit(scopes.find(s=>s.name==='rv32_graphics').id);
};
