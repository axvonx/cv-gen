/** @jest-environment jsdom */
import fs from 'fs';
const {route, signature} = require('./cv-gen-schematic.cjs');
const noop = () => {};
const ctx = new Proxy({}, {get: (_t,p)=>p==='measureText'?text=>({width:String(text).length*7}):p==='canvas'?{}:noop,set:()=>true});
HTMLCanvasElement.prototype.getContext = () => ctx;
jest.mock('codemirror');
test('build and round trip CircuitVerse project', () => {
  const CodeMirror = require('codemirror');
  CodeMirror.fromTextArea.mockReturnValue({setValue:noop});
  const {setup} = require('../src/setup');
  const {newCircuit, switchCircuit, scopeList} = require('../src/circuit');
  const {verilogModeGet} = require('../src/Verilog2CV');
  const types = require('../src/VerilogClasses').default;
  require('./cv-gen-memory.cjs').install(types,require('../src/sequential/RAM').default,require('../src/modules/Multiplexer').default,require('../src/modules/ConstantVal').default,require('../src/sequential/ROM').default,require('../src/modules/Splitter').default);
  const {generateSaveData} = require('../src/data/save');
  const load = require('../src/data/load').default;
  const SubCircuit = require('../src/subcircuit').default;
  const Input = require('../src/modules/Input').default;
  const Output = require('../src/modules/Output').default;
  const Clock = require('../src/sequential/Clock').default;
  const graph = JSON.parse(fs.readFileSync(process.env.CVGEN_GRAPH,'utf8'));
  // Pinned importer maps clk/clock to a Clock instead of a module input.
  const rename = {clk:'__cvgen_port_clk', clock:'__cvgen_port_clock'};
  const patch = (mod) => {
    for (const d of Object.values(mod.devices)) if (d.type==='Input' && rename[d.net]) d.net=rename[d.net];
    for (const edge of mod.connectors) for (const end of ['from','to']) {
      const dev=mod.devices[edge[end].id];
      if (dev.type==='Subcircuit' && rename[edge[end].port]) edge[end].port=rename[edge[end].port];
    }
    for (const child of Object.values(mod.subcircuits||{})) patch(child);
  };
  patch(graph);
  setup();
  const Node=require('../src/node').default;
  const originalConnect=Node.prototype.connect;
  Node.prototype.connect=Node.prototype.connectWireLess;
  const initialScope=globalScope.id;
  // Generated gates must be an ordinary visible circuit. A Verilog circuit
  // activates CircuitVerse's code editor and hides its canvas on selection.
  const top = newCircuit(graph.name);
  const signatures=new Map();
  const reports={};
  function importGraph(mod, scope, aliases={}) {
    const parentId = scope.id;
    for (const [name,child] of Object.entries(mod.subcircuits||{})) {
      const childScope = newCircuit(name);
      aliases[name] = childScope.id;
      importGraph(child,childScope,aliases);
      switchCircuit(parentId);
    }
    const devices={};
    for (const [id,dev] of Object.entries(mod.devices)) {
      let instance;
      if (dev.type==='Subcircuit') {
        const target=scopeList[aliases[dev.celltype]];
        if (!target) throw Error(`unknown subcircuit ${dev.celltype}`);
        const block=new SubCircuit(0,0,scope,target.id);
        instance={getPort: (name)=>{
          const index=target.Input.findIndex(p=>p.label===name);
          if (index>=0) return block.inputNodes[index];
          const out=target.Output.findIndex(p=>p.label===name);
          if (out>=0) return block.outputNodes[out];
        }};
      } else {
        if (!types[dev.type]) throw Error(`unsupported CircuitVerse device ${dev.type} (${id})`);
        instance=new types[dev.type](dev);
      }
      devices[id]=instance;
    }
    for (const [i,edge] of mod.connectors.entries()) {
      const a=devices[edge.from.id]?.getPort(edge.from.port);
      const b=devices[edge.to.id]?.getPort(edge.to.port);
      if (!a || !b) throw Error(`connector ${i}: ${edge.from.id}.${edge.from.port} -> ${edge.to.id}.${edge.to.port} has an unsupported port`);
      a.cvgenFlowOut=true;b.cvgenFlowIn=true;
      a.connect(b);
    }
    reports[scope.name]=route(scope,moduleList,Node);
    signatures.set(scope.id,signature(scope,moduleList));
    scope.layout.width=200;
    scope.layout.height=80+Math.max(scope.Input.length,scope.Output.length)*40;
    scope.Input.forEach((p,i)=>{p.layoutProperties.x=0;p.layoutProperties.y=40+i*40;});
    scope.Output.forEach((p,i)=>{p.layoutProperties.x=200;p.layoutProperties.y=40+i*40;});
  }
  importGraph(graph,top);
  for (const scope of Object.values(scopeList)) for (const port of scope.Input) {
    for (const [original, temporary] of Object.entries(rename)) if (port.label===temporary) port.label=original;
  }
  const input = top.Input.map(x=>({label:x.label,width:x.bitWidth}));
  const output = top.Output.map(x=>({label:x.label,width:x.bitWidth}));
  expect(input.map(x=>x.label).sort()).toEqual(Object.values(graph.devices).filter(x=>x.type==='Input').map(x=>Object.entries(rename).find(([,v])=>v===x.net)?.[0]||x.net).sort());
  expect(output.map(x=>x.label).sort()).toEqual(Object.values(graph.devices).filter(x=>x.type==='Output').map(x=>Object.entries(rename).find(([,v])=>v===x.net)?.[0]||x.net).sort());
  delete scopeList[initialScope];
  const demo = newCircuit('Demo');
  const block = new SubCircuit(600,400,demo,top.id);
  const clocks = new Set(JSON.parse(process.env.CVGEN_CLOCKS));
  input.forEach((port,i)=>{
    const control = clocks.has(port.label) ? new Clock(150,180+i*90) : new Input(150,180+i*90,undefined,undefined,port.width);
    control.label = port.label;
    control.output1.connect(block.inputNodes[i]);
  });
  output.forEach((port,i)=>{
    const readout = new Output(1000,180+i*90,undefined,undefined,port.width);
    readout.label=port.label;
    block.outputNodes[i].connect(readout.inp1);
  });
  reports.Demo=route(demo,moduleList,Node,{});
  signatures.set(demo.id,signature(demo,moduleList));
  // Open the generated gate-level scope; Demo remains available as the block view.
  switchCircuit(top.id);
  const data = JSON.parse(generateSaveData(graph.name));
  Node.prototype.connect=originalConnect;
  expect(data.scopes.some(s=>s.name===graph.name)).toBe(true);
  expect(data.scopes.some(s=>s.name==='Demo')).toBe(true);
  load(data);
  expect(verilogModeGet()).toBe(false);
  expect(globalScope.name).toBe(graph.name);
  for(const scope of Object.values(require('../src/circuit').scopeList)){
    const saved=data.scopes.find(s=>s.id===scope.id);
    for(let pass=0;pass<3;pass++){
      for(const wire of scope.wires.slice())wire.update();
      for(const node of scope.allNodes.slice())node.update();
    }
    for(const kind of moduleList)expect(scope[kind].length).toBe((saved[kind]||[]).length);
    expect(signature(scope,moduleList)).toEqual(signatures.get(scope.id));
    for(const node of scope.allNodes)for(const peer of node.connections){
      if(peer.scope===scope)expect(node.bitWidth).toBe(peer.bitWidth);
    }
  }
  const roundtrip = JSON.parse(generateSaveData(graph.name));
  expect(roundtrip.scopes.map(s=>s.name).sort()).toEqual(data.scopes.map(s=>s.name).sort());
  fs.writeFileSync(process.env.CVGEN_PROJECT,JSON.stringify(roundtrip));
  if(process.env.CVGEN_LAYOUT_REPORT)fs.writeFileSync(process.env.CVGEN_LAYOUT_REPORT,JSON.stringify(reports));
  if(process.env.CVGEN_RENDER){
    const {findDimensions}=require('../src/canvasApi');
    const simulationArea=require('../src/simulationArea').default;
    const C2S=require('../src/canvas2svg').default;
    findDimensions(globalScope);
    width=simulationArea.maxWidth-simulationArea.minWidth+400;
    height=simulationArea.maxHeight-simulationArea.minHeight+100;
    globalScope.scale=1;
    globalScope.ox=200-simulationArea.minWidth;
    globalScope.oy=50-simulationArea.minHeight;
    simulationArea.context=new C2S(width,height);
    simulationArea.context.fillStyle='#ffffff';
    simulationArea.context.fillRect(0,0,width,height);
    for(const kind of renderOrder)for(const element of globalScope[kind])element.draw();
    const svg=simulationArea.context.getSerializedSvg();
    fs.writeFileSync(process.env.CVGEN_RENDER,svg.replace('xmlns:xlink="http://www.w3.org/1999/xlink"',''));
  }
});
