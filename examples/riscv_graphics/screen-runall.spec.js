/** @jest-environment jsdom */
import fs from 'fs';
const noop=()=>{};
HTMLCanvasElement.prototype.getContext=()=>new Proxy({}, {get:(_t,p)=>p==='measureText'?t=>({width:String(t).length*7}):p==='canvas'?{}:noop,set:()=>true});
jest.mock('codemirror');
test('Run All draws the CPU framebuffer on the native screen',()=>{
 require('codemirror').fromTextArea.mockReturnValue({setValue:noop});
 require('../src/setup').setup();
 require('../src/data/load').default(JSON.parse(fs.readFileSync(process.env.RV_SCREEN_INPUT,'utf8')));
 const circuit=require('../src/circuit');
 const scope=Object.values(circuit.scopeList).find(s=>s.name==='rv32_graphics');
 circuit.switchCircuit(scope.id);
 const {errorDetectedGet,errorDetectedSet}=require('../src/engine');
 errorDetectedSet(false);
 const result=require('../src/testbench').runAll(scope.testbenchData.testData,scope);
 expect(errorDetectedGet()).toBe(false);
 expect(result.summary.passed).toBe(result.summary.total);
 const screen=scope.RGBLedMatrix[0];
 for(const pin of [...screen.rowEnableNodes,...screen.columnColorNodes]){
  expect(pin.value).not.toBeUndefined();
 }
 const expected=[...fs.readFileSync(process.env.RV_SCREEN_EXPECTED)].map(v=>v*0x010101);
 expect(screen.colors.flat()).toEqual(expected);
 // Draw the real native matrix after Run All, rather than reconstructing a PNG.
 const area=require('../src/simulationArea').default;
 const C2S=require('../src/canvas2svg').default;
 width=360;height=360;
 scope.scale=1;scope.ox=180-screen.x;scope.oy=180-screen.y;
 area.context=new C2S(width,height);
 area.context.fillStyle='#fff';area.context.fillRect(0,0,width,height);
 screen.customDraw();
 fs.writeFileSync(process.env.RV_SCREEN_SVG,area.context.getSerializedSvg().replace('xmlns:xlink="http://www.w3.org/1999/xlink"',''));
 fs.writeFileSync(process.env.RV_SCREEN_REPORT,JSON.stringify({
  passed:result.summary.passed,total:result.summary.total,screenPixels:256,
 }));
},300000);
