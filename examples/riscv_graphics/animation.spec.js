/** @jest-environment jsdom */
// Verification deliberately uses the same clockTick as the browser interval.
import fs from 'fs';
const noop=()=>{};
HTMLCanvasElement.prototype.getContext=()=>new Proxy({}, {
 get:(_t,p)=>p==='measureText'?t=>({width:String(t).length*7}):p==='canvas'?{}:noop,
 set:()=>true,
});
jest.mock('codemirror');
test('saved project boots and animates through ordinary automatic clock ticks',()=>{
 require('codemirror').fromTextArea.mockReturnValue({setValue:noop});
 require('../src/setup').setup();
 const load=require('../src/data/load').default;
 const circuit=require('../src/circuit');
 const area=require('../src/simulationArea').default;
 const {play,errorDetectedGet,errorDetectedSet}=require('../src/engine');
 load(JSON.parse(fs.readFileSync(process.env.RV_ANIMATION_INPUT,'utf8')));
 let demo=Object.values(circuit.scopeList).find(s=>s.name==='Demo');
 for(const input of demo.Input)input.state=input.label==='run'?1:0;
 circuit.switchCircuit(demo.id);
 area.clockEnabled=true;
 area.changeClockTime(50);
 const document=JSON.parse(require('../src/data/save').generateSaveData('RISC-V — automatic camera sweep'));
 document.name='RISC-V — automatic camera sweep';
 expect(document.focussedCircuit).toBe(demo.id);
 expect(document.clockEnabled).toBe(true);
 expect(document.timePeriod).toBe(50);
 // A fresh load discards all volatile CPU and framebuffer RAM state.
 load(document);
 demo=Object.values(circuit.scopeList).find(s=>s.name==='Demo');
 expect(globalScope.id).toBe(demo.id);
 expect(demo.Input.find(p=>p.label==='run').state).toBe(1);
 expect(demo.Clock).toHaveLength(1);
 const outputs=Object.fromEntries(demo.Output.map(p=>[p.label,p]));
 const read=n=>outputs[n].inp1.value;
 errorDetectedSet(false);
 play();
 const tick=require('../src/utils').clockTick;
 const expected=[...fs.readFileSync(process.env.RV_ANIMATION_EXPECTED)];
 expect(expected).toHaveLength(8192);
 expect(expected.slice(0,256)).not.toEqual(expected.slice(256,512));
 const frames=[];
 const started=performance.now();
 let ticks=0;
 for(;ticks<100000 && frames.length<2;ticks++){
  tick();
  if(errorDetectedGet())throw Error(`CircuitVerse error at clock tick ${ticks}`);
  expect(read('fault')).toBe(0);
  expect(read('done')).toBe(0);
  if(read('result')===frames.length+1){
   const matrix=demo.RGBLedMatrix[0];
   for(const pin of [...matrix.rowEnableNodes,...matrix.columnColorNodes])expect(pin.value).not.toBeUndefined();
   const pixels=matrix.colors.flat();
   expect(pixels).toEqual(expected.slice(frames.length*256,(frames.length+1)*256).map(v=>v*0x010101));
   frames.push({number:frames.length+1,ticks:ticks+1,elapsedMs:performance.now()-started});
  }
 }
 expect(frames).toHaveLength(2);
 // Save the pristine boot configuration, never a test trace or stopped snapshot.
 fs.writeFileSync(process.env.RV_ANIMATION_OUTPUT,JSON.stringify(document));
 fs.writeFileSync(process.env.RV_ANIMATION_REPORT,JSON.stringify({frames,ticks,pixelsVerified:512,automaticClock:true,fault:read('fault')}));
 clearInterval(area.ClockInterval);
},600000);
