/** @jest-environment jsdom */
import fs from 'fs';
const noop=()=>{};
HTMLCanvasElement.prototype.getContext=()=>new Proxy({}, {get:(_t,p)=>p==='measureText'?t=>({width:String(t).length*7}):p==='canvas'?{}:noop,set:()=>true});
jest.mock('codemirror');
test('attach and round trip live framebuffer screen',()=>{
 require('codemirror').fromTextArea.mockReturnValue({setValue:noop});
 require('../src/setup').setup();
 const load=require('../src/data/load').default;
 const circuit=require('../src/circuit');
 load(JSON.parse(fs.readFileSync(process.env.RV_SCREEN_INPUT,'utf8')));
 const Node=require('../src/node').default;
 const {route,signature}=require('./cv-gen-schematic.cjs');
 const api={
  ...circuit,Node,route,kinds:moduleList,
  ...Object.fromEntries(['Input','Output','Splitter','Decoder','AndGate','ConstantVal','RGBLedMatrix'].map(n=>[n,require(`../src/modules/${n}`).default])),
  RAM:require('../src/sequential/RAM').default,
  SubCircuit:require('../src/subcircuit').default,
 };
 require('./rv32-screen.cjs').install(api,Object.values(circuit.scopeList));
 Object.assign(api,require('../src/engine'));
 require('./rv32-screen.cjs').testWrites(api,Object.values(circuit.scopeList));
 circuit.switchCircuit(Object.values(circuit.scopeList).find(s=>s.name==='rv32_graphics').id);
 const before=new Map(Object.values(circuit.scopeList).map(s=>[s.name,signature(s,moduleList)]));
 const data=JSON.parse(require('../src/data/save').generateSaveData('rv32_graphics'));
 load(data);
 for(const s of Object.values(circuit.scopeList)){
  if(['rv32_graphics','Demo'].includes(s.name))expect(s.RGBLedMatrix).toHaveLength(1);
  for(let pass=0;pass<3;pass++){
   for(const w of s.wires.slice())w.update();
   for(const n of s.allNodes.slice())n.update();
  }
  expect(signature(s,moduleList)).toEqual(before.get(s.name));
  for(const n of s.allNodes)for(const p of n.connections)expect(n.bitWidth).toBe(p.bitWidth);
 }
 fs.writeFileSync(process.env.RV_SCREEN_OUTPUT,require('../src/data/save').generateSaveData('rv32_graphics'));
},300000);
