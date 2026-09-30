import fs from 'fs';
import { performance } from 'node:perf_hooks';
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

import { errorDetectedGet, errorDetectedSet } from '../src/engine';
vi.mock('codemirror', async (importOriginal) => {
  const actual = await importOriginal();
  return {...actual, fromTextArea:vi.fn(()=>({setValue:()=>{}}))};
});
vi.mock('codemirror-editor-vue3',()=>({defineSimpleMode:vi.fn()}));
test('simulate canonical project', async()=>{
  Object.defineProperty(window,'crypto',{value:webcrypto,configurable:true});
  const pinia=createPinia();setActivePinia(pinia);
  const router=createRouter({history:createWebHistory(),routes});
  const elem=document.createElement('div');document.body.appendChild(elem);
  global.document.createRange=vi.fn(()=>({setEnd:vi.fn(),setStart:vi.fn(),getBoundingClientRect:vi.fn(()=>({x:0,y:0,width:0,height:0,top:0,right:0,bottom:0,left:0})),getClientRects:vi.fn(()=>({item:vi.fn(()=>null),length:0,[Symbol.iterator]:vi.fn(()=>[])}))}));
  global.globalScope=global.globalScope||{};
  mount(simulator,{global:{plugins:[pinia,router,i18n,vuetify]},attachTo:elem});
  setup();
  const request=JSON.parse(fs.readFileSync(process.env.RV_REQUEST,'utf8'));
  const started=performance.now();
  const projectData=JSON.parse(fs.readFileSync(request.project,'utf8'));
  const loaded=await importCanonical(projectData);
  if(!loaded.success)throw Error(`canonical loader: ${loaded.errors.join('; ')}`);
  const {scopeList:loadedScopes}=await import('../src/circuit');
  const top=Object.values(loadedScopes).find(s=>s.name==='rv32_graphics');
  if(!top)throw Error('missing rv32_graphics');
  const loadMs=performance.now()-started;
  const {play}=await import('../src/engine');
  const result=(await import('./rv32-runtime.cjs')).default.execute(top,play,errorDetectedGet,errorDetectedSet,request);
  fs.writeFileSync(process.env.RV_REPORT,JSON.stringify({...result,load_ms:loadMs}));
},1800000);
