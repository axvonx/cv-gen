/** @jest-environment jsdom */
// Diagnostic renderer for an existing legacy project, using the pinned native
// CircuitVerse drawing code. Copy next to simulator/spec before invoking Jest.
import fs from 'fs';
const noop=()=>{};
const ctx=new Proxy({}, {get:(_t,p)=>p==='measureText'?text=>({width:String(text).length*7}):p==='canvas'?{}:noop,set:()=>true});
HTMLCanvasElement.prototype.getContext=()=>ctx;
jest.mock('codemirror');
test('render an existing project',()=>{
  require('codemirror').fromTextArea.mockReturnValue({setValue:noop});
  require('../src/setup').setup();
  const {switchCircuit}=require('../src/circuit');
  require('../src/data/load').default(JSON.parse(fs.readFileSync(process.env.CVGEN_PROJECT,'utf8')));
  const {signature}=require('./cv-gen-schematic.cjs');
  const scopes=Object.values(require('../src/circuit').scopeList);
  for(const loaded of scopes){
    const before=signature(loaded,moduleList);
    const counts=moduleList.map(kind=>loaded[kind].length);
    for(let pass=0;pass<3;pass++){
      for(const wire of loaded.wires.slice())wire.update();
      for(const node of loaded.allNodes.slice())node.update();
    }
    expect(signature(loaded,moduleList)).toEqual(before);
    expect(moduleList.map(kind=>loaded[kind].length)).toEqual(counts);
    for(const node of loaded.allNodes)for(const peer of node.connections)if(peer.scope===loaded)expect(node.bitWidth).toBe(peer.bitWidth);
  }
  const scope=Object.values(require('../src/circuit').scopeList).find(s=>s.name===process.env.CVGEN_RENDER_SCOPE);
  if(!scope)throw Error(`scope ${process.env.CVGEN_RENDER_SCOPE} not found`);
  switchCircuit(scope.id);
  const {findDimensions}=require('../src/canvasApi');
  const simulationArea=require('../src/simulationArea').default;
  const C2S=require('../src/canvas2svg').default;
  findDimensions(scope);
  width=simulationArea.maxWidth-simulationArea.minWidth+400;
  height=simulationArea.maxHeight-simulationArea.minHeight+100;
  scope.scale=1;scope.ox=200-simulationArea.minWidth;scope.oy=50-simulationArea.minHeight;
  simulationArea.context=new C2S(width,height);
  simulationArea.context.fillStyle='#fff';simulationArea.context.fillRect(0,0,width,height);
  for(const kind of renderOrder)for(const element of scope[kind])element.draw();
  fs.writeFileSync(process.env.CVGEN_RENDER,simulationArea.context.getSerializedSvg().replace('xmlns:xlink="http://www.w3.org/1999/xlink"',''));
});
