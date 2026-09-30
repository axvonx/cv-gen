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

import { importCanonical } from '../src/data/importCanonical';

vi.mock('codemirror', async (importOriginal) => {
  const actual = await importOriginal();
  return {...actual, fromTextArea:vi.fn(()=>({setValue:()=>{}}))};
});
vi.mock('codemirror-editor-vue3',()=>({defineSimpleMode:vi.fn()}));
test('attach native canonical screen', async()=>{
  Object.defineProperty(window,'crypto',{value:webcrypto,configurable:true});
  const pinia=createPinia();setActivePinia(pinia);
  const router=createRouter({history:createWebHistory(),routes});
  const elem=document.createElement('div');document.body.appendChild(elem);
  global.document.createRange=vi.fn(()=>({setEnd:vi.fn(),setStart:vi.fn(),getBoundingClientRect:vi.fn(()=>({x:0,y:0,width:0,height:0,top:0,right:0,bottom:0,left:0})),getClientRects:vi.fn(()=>({item:vi.fn(()=>null),length:0,[Symbol.iterator]:vi.fn(()=>[])}))}));
  global.globalScope=global.globalScope||{};
  mount(simulator,{global:{plugins:[pinia,router,i18n,vuetify]},attachTo:elem});
  setup();
  const data=JSON.parse(fs.readFileSync(process.env.RV_SCREEN_INPUT,'utf8'));
  const loaded=await importCanonical(data);
  if(!loaded.success)throw Error(loaded.errors.join('; '));
  const circuit=await import('../src/circuit');
  const api={...circuit, kinds:(await import('../src/metadata')).moduleList,
   Node:(await import('../src/node')).default,
   route:(await import('./cv-gen-schematic.cjs')).default.route,
   SubCircuit:(await import('../src/subcircuit')).default};
  for(const name of ['Input','Output','Splitter','Decoder','AndGate','ConstantVal','RGBLedMatrix']){
   api[name]=(await import(`../src/modules/${name}.js`)).default;
  }
  api.RAM=(await import('../src/sequential/RAM')).default;
  (await import('./rv32-screen.cjs')).default.install(api,Object.values(circuit.scopeList));
  Object.assign(api,await import('../src/engine'));
  (await import('./rv32-screen.cjs')).default.testWrites(api,Object.values(circuit.scopeList));
  for(const [id,scope] of Object.entries(circuit.scopeList)){
   if(scope.name==='Main')delete circuit.scopeList[id];
   else {scope.id=String(scope.id);for(const sub of scope.SubCircuit||[])sub.id=String(sub.id);}
  }
  const {canonicaliseProject}=await import('../src/data/canonical');
  const result=await canonicaliseProject(Object.values(circuit.scopeList));
  const roundtrip=await importCanonical(result);
  if(!roundtrip.success)throw Error(roundtrip.errors.join('; '));
  for(const scope of Object.values(circuit.scopeList)){
   if(['rv32_graphics','Demo'].includes(scope.name))expect(scope.RGBLedMatrix).toHaveLength(1);
  }
  fs.writeFileSync(process.env.RV_SCREEN_OUTPUT,JSON.stringify(result));
},300000);
