/** @jest-environment jsdom */
// Native execution timing excludes project loading, loader and pixel readback.
import fs from 'fs';
const noop=()=>{};
const ctx=new Proxy({}, {get:(_t,p)=>p==='measureText'?()=>({width:0}):p==='canvas'?{}:noop,set:()=>true});
HTMLCanvasElement.prototype.getContext=()=>ctx;
jest.mock('codemirror');
test('run loaded RISC-V program and benchmark native execution',()=>{
 require('codemirror').fromTextArea.mockReturnValue({setValue:noop});
 require('../src/setup').setup();
 const request=JSON.parse(fs.readFileSync(process.env.RV_REQUEST,'utf8'));
 const started=performance.now();
 require('../src/data/load').default(JSON.parse(fs.readFileSync(request.project,'utf8')));
 const scopes=require('../src/circuit').scopeList;
 const scope=Object.values(scopes).find(s=>s.name==='rv32_graphics');
 if(!scope)throw Error('missing rv32_graphics scope');
 require('../src/circuit').switchCircuit(scope.id);
 const {play,errorDetectedGet,errorDetectedSet}=require('../src/engine');
 const loadMs=performance.now()-started;
 const result=require('./rv32-runtime.cjs').execute(scope,play,errorDetectedGet,errorDetectedSet,request);
 fs.writeFileSync(process.env.RV_REPORT,JSON.stringify({...result,load_ms:loadMs}));
},1800000);
