import fs from 'fs';
import { webcrypto } from 'node:crypto';
import { createPinia, setActivePinia } from 'pinia';
import { mount } from '@vue/test-utils';
import { createRouter, createWebHistory } from 'vue-router';
import i18n from '#/locales/i18n';
import { routes } from '#/router';
import vuetify from '#/plugins/vuetify';
import simulator from '#/pages/simulator.vue';
import { setup } from '../src/setup';
import { newCircuit, scopeList } from '../src/circuit';
import { YosysJSON2CV } from '../src/Verilog2CV';
import { canonicaliseProject } from '../src/data/canonical';
import { importCanonical } from '../src/data/importCanonical';
import Node from '../src/node';
import { moduleList } from '../src/metadata';
import schematic from './cv-gen-schematic.cjs';
import memory from './cv-gen-memory.cjs';
import types from '../src/VerilogClasses';
import RAM from '../src/sequential/RAM';
import Rom from '../src/sequential/ROM';
import Splitter from '../src/modules/Splitter';
import Multiplexer from '../src/modules/Multiplexer';
import ConstantVal from '../src/modules/ConstantVal';
import SubCircuit from '../src/subcircuit';
import Input from '../src/modules/Input';
import Output from '../src/modules/Output';
import Clock from '../src/sequential/Clock';

vi.mock('codemirror', async (importOriginal) => {
  const actual = await importOriginal();
  return {...actual, fromTextArea:vi.fn(()=>({setValue:()=>{}}))};
});
vi.mock('codemirror-editor-vue3',()=>({defineSimpleMode:vi.fn()}));

test('canonical CircuitVerse build and round trip', async()=>{
  Object.defineProperty(window,'crypto',{value:webcrypto,configurable:true});
  const pinia=createPinia(); setActivePinia(pinia);
  const router=createRouter({history:createWebHistory(),routes});
  const elem=document.createElement('div'); document.body.appendChild(elem);
  global.document.createRange=vi.fn(()=>({setEnd:vi.fn(),setStart:vi.fn(),getBoundingClientRect:vi.fn(()=>({x:0,y:0,width:0,height:0,top:0,right:0,bottom:0,left:0})),getClientRects:vi.fn(()=>({item:vi.fn(()=>null),length:0,[Symbol.iterator]:vi.fn(()=>[])}))}));
  global.globalScope=global.globalScope||{};
  mount(simulator,{global:{plugins:[pinia,router,i18n,vuetify]},attachTo:elem});
  setup();
  const graph=JSON.parse(fs.readFileSync(process.env.CVGEN_GRAPH,'utf8'));
  const clocks=new Set(JSON.parse(process.env.CVGEN_CLOCKS));
  const rename={clk:'__cvgen_port_clk',clock:'__cvgen_port_clock'};
  const patch=(mod)=>{
    for(const d of Object.values(mod.devices))if(d.type==='Input'&&rename[d.net])d.net=rename[d.net];
    for(const edge of mod.connectors)for(const end of ['from','to']){
      const dev=mod.devices[edge[end].id];
      if(dev.type==='Subcircuit'&&rename[edge[end].port])edge[end].port=rename[edge[end].port];
    }
    for(const child of Object.values(mod.subcircuits||{}))patch(child);
  };
  patch(graph);
  memory.install(types,RAM,Multiplexer,ConstantVal,Rom,Splitter);
  const originalConnect=Node.prototype.connect;
  Node.prototype.connect=Node.prototype.connectWireLess;
  globalThis.newCircuit=newCircuit; // pinned v1 importer refers to this missing global
  const top=newCircuit(graph.name);
  YosysJSON2CV(graph,top,graph.name,{},true);
  // The native importer creates child scopes in Verilog editor mode. The
  // canonical artifact contains generated gates, so expose each as a canvas.
  for(const scope of Object.values(scopeList)){
    scope.verilogMetadata.isVerilogCircuit=false;
    scope.verilogMetadata.isMainCircuit=false;
  }
  for(const scope of Object.values(scopeList))for(const port of scope.Input){
    for(const [original,temporary] of Object.entries(rename))if(port.label===temporary)port.label=original;
  }
  for(const scope of Object.values(scopeList))if(scope.name!=='Main')schematic.route(scope,moduleList,Node);
  const input=top.Input.map(x=>({label:x.label,width:x.bitWidth}));
  const output=top.Output.map(x=>({label:x.label,width:x.bitWidth}));
  const demo=newCircuit('Demo');
  const block=new SubCircuit(600,400,demo,top.id);
  input.forEach((port,i)=>{
    const control=clocks.has(port.label)?new Clock(150,180+i*90):new Input(150,180+i*90,demo,undefined,port.width);
    control.label=port.label;
    control.output1.connect(block.inputNodes[i]);
  });
  output.forEach((port,i)=>{
    const readout=new Output(1000,180+i*90,demo,undefined,port.width);
    readout.label=port.label;
    block.outputNodes[i].connect(readout.inp1);
  });
  schematic.route(demo,moduleList,Node,{});
  Node.prototype.connect=originalConnect;
  for(const [id,scope] of Object.entries(scopeList)){
    if(scope.name==='Main')delete scopeList[id];
    else {scope.scale=1;scope.id=String(scope.id);for(const sub of scope.SubCircuit||[])sub.id=String(sub.id);}
  }
  const data=await canonicaliseProject(Object.values(scopeList));
  if(data.formatVersion!=='v1')throw Error('canonical serializer returned wrong format');
  fs.writeFileSync(process.env.CVGEN_PROJECT,JSON.stringify(data));
  const loaded=await importCanonical(data);
  if(!loaded.success)throw Error(`canonical loader: ${loaded.errors.join('; ')}`);
  fs.writeFileSync(process.env.CVGEN_PROJECT,JSON.stringify(data));
},300000);
