/** @jest-environment jsdom */
import fs from 'fs';
const noop=()=>{};
HTMLCanvasElement.prototype.getContext=()=>new Proxy({}, {
 get:(_t,p)=>p==='measureText'?t=>({width:String(t).length*7}):p==='canvas'?{}:noop,set:()=>true,
});
jest.mock('codemirror');
test('native ROM screen autoplays all camera frames and wraps',()=>{
 require('codemirror').fromTextArea.mockReturnValue({setValue:noop});
 require('../src/setup').setup();
 const load=require('../src/data/load').default;
 const circuit=require('../src/circuit');
 const area=require('../src/simulationArea').default;
 const Node=require('../src/node').default;
 const Matrix=require('../src/modules/RGBLedMatrix').default;
 const {route}=require('./cv-gen-schematic.cjs');
 const {play,errorDetectedGet,errorDetectedSet}=require('../src/engine');
 const expected=[...fs.readFileSync(process.env.RV_ANIMATION_EXPECTED)];
 const size=Number(process.env.RV_ANIMATION_SIZE||16);
 const rowBits=Math.log2(size),framePixels=size*size;
 expect(expected).toHaveLength(32*framePixels);
 load(JSON.parse(fs.readFileSync(process.env.RV_ANIMATION_INPUT,'utf8')));
 let demo=Object.values(circuit.scopeList).find(s=>s.name==='Demo');
 circuit.switchCircuit(demo.id);
 const connect=Node.prototype.connect;
 Node.prototype.connect=Node.prototype.connectWireLess;
 // Recover electrical nets before adding the matrix and routing the dashboard.
 const seen=new Set(),nets=[];
 for(const start of demo.allNodes){
  if(seen.has(start))continue;
  const stack=[start],net=[];
  while(stack.length){
   const n=stack.pop();if(seen.has(n))continue;
   seen.add(n);net.push(n);stack.push(...n.connections);
  }
  nets.push(net.filter(n=>n.type!==2));
 }
 for(const n of demo.allNodes)n.connections=[];
 demo.wires=[];
 for(const n of demo.allNodes.slice())if(n.type===2)n.delete();
 for(const net of nets)for(const n of net.slice(1))net[0].connect(n);
 const screen=new Matrix(0,0,demo,{rows:size,columns:size,ledSize:2,showGrid:false,
  colors:Array.from({length:size},(_,r)=>expected.slice(r*size,r*size+size).map(v=>v*0x010101))});
 screen.label=`SCREEN — ${size} × ${size} C camera sweep (ROM playback)`;
 const row=demo.Output.find(p=>p.label==='row_index');
 const Decoder=require('../src/modules/Decoder').default;
 const decoder=new Decoder(0,0,demo,'RIGHT',rowBits);
 row.inp1.connect(decoder.input);
 for(let i=0;i<size;i++){
  decoder.output1[i].connect(screen.rowEnableNodes[i]);
  demo.Output.find(p=>p.label===`color_${i}`).inp1.connect(screen.columnColorNodes[i]);
 }
 route(demo,moduleList,Node);
 Node.prototype.connect=connect;
 area.clockEnabled=true;area.changeClockTime(50);
 const document=JSON.parse(require('../src/data/save').generateSaveData('C camera sweep — passive ROM animation'));
 document.name='C camera sweep — passive ROM animation';
 load(document);
 demo=Object.values(circuit.scopeList).find(s=>s.name==='Demo');
 expect(globalScope.id).toBe(demo.id);
 expect(area.clockEnabled).toBe(true);expect(area.timePeriod).toBe(50);
 errorDetectedSet(false);play();
 const tick=require('../src/utils').clockTick;
 const output=demo.Output.find(p=>p.label==='frame');
 const rowOutput=demo.Output.find(p=>p.label==='row_index');
 const matrix=demo.RGBLedMatrix[0];
 expect(matrix.rows).toBe(size);expect(matrix.columns).toBe(size);
 expect(matrix.colors.flat()).toEqual(expected.slice(0,framePixels).map(v=>v*0x010101));
 let previous=-1,completed=0;
 const ticksTotal=33*size*2;
 for(let ticks=0;ticks<ticksTotal;ticks++){
  tick();
  if(errorDetectedGet())throw Error(`screen error at tick ${ticks}`);
  const frame=output.inp1.value;
  if(rowOutput.inp1.value===size-1 && frame!==previous){
   // The last row is painted; every pixel belongs to this complete frame.
   const pixels=matrix.colors.flat();
   expect(frame).toBe(completed&31);
   expect(pixels).toEqual(expected.slice(frame*framePixels,(frame+1)*framePixels).map(v=>v*0x010101));
   previous=frame;completed++;
  }
  for(const pin of [...matrix.rowEnableNodes,...matrix.columnColorNodes])expect(pin.value).not.toBeUndefined();
 }
 expect(completed).toBe(33); // all 32 frames, wrap, and first frame again
 expect(previous).toBe(0);
 fs.writeFileSync(process.env.RV_ANIMATION_OUTPUT,JSON.stringify(document));
 if(process.env.RV_ANIMATION_REPORT)fs.writeFileSync(process.env.RV_ANIMATION_REPORT,JSON.stringify({
  size,framesVerified:completed,pixelsVerified:completed*framePixels,clockMs:50,
  nominalFrameSeconds:size*0.1,automaticClock:true,errors:false,
 }));
 clearInterval(area.ClockInterval);
},300000);
