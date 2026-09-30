const fs = require('fs');
const path = require('path');
const os = require('os');
const cp = require('child_process');
const { yosys2digitaljs } = require('yosys2digitaljs/core');

function fail(message) { throw Error(message); }
function quote(value) { return '"' + String(value).replaceAll('\\', '\\\\').replaceAll('"', '\\"') + '"'; }
function modules(graph) { return [graph, ...Object.values(graph.subcircuits || {})]; }
function validate(graph, ports, clocks) {
  const expected = new Map(Object.entries(ports));
  const actual = new Map();
  for (const [mi, mod] of modules(graph).entries()) {
    for (const [id, dev] of Object.entries(mod.devices || {})) {
      if (!dev || typeof dev.type !== 'string') fail(`module ${mi}: device ${id} has no type`);
      if (mi === 0 && ['Input','Output'].includes(dev.type)) actual.set(`${dev.type}:${dev.net}`, dev.bits);
    }
    for (const [id, dev] of Object.entries(mod.devices || {})) {
      if (dev.type === 'Output' && !(mod.connectors || []).some(e=>e.to.id===id)) fail(`module ${mi}: output ${dev.net} is undriven`);
    }
    for (const [i, edge] of (mod.connectors || []).entries()) {
      for (const end of ['from','to']) {
        const p = edge[end];
        if (!p || !mod.devices[p.id] || !p.port) fail(`module ${mi}: connector ${i} has invalid ${end} endpoint`);
      }
    }
  }
  for (const [name, port] of expected) {
    const key = `${port.direction === 'input' ? 'Input' : 'Output'}:${name}`;
    if (actual.get(key) !== port.bits.length) fail(`top port ${name} width or direction lost: expected ${port.bits.length}, got ${actual.get(key)}`);
  }
  if (actual.size !== expected.size) fail(`top port count mismatch: expected ${expected.size}, got ${actual.size}`);
  for (const clock of clocks) if (expected.get(clock)?.direction !== 'input' || expected.get(clock)?.bits.length !== 1) fail(`clock ${clock} must be a 1-bit top input`);
}
function main() {
  const req = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const scratch = path.dirname(process.argv[2]);
  const yosysScript = path.join(scratch, 'synth.ys');
  const netlist = req.netlist;
  const read = req.sources.map(file => `read_verilog ${file.endsWith('.sv') ? '-sv ' : ''}${req.includes.map(p=>'-I '+p).join(' ')} ${Object.entries(req.defines).map(([k,v])=>'-D '+`${k}=${v}`).join(' ')} ${quote(file)}`);
  const params = Object.entries(req.parameters).map(([k,v]) => `-chparam ${k} ${v}`).join(' ');
  fs.writeFileSync(yosysScript, [...read, `hierarchy -top ${req.top} ${params}`, 'proc', 'opt', 'memory -nomap', 'wreduce', 'pmuxtree', 'simplemap t:$reduce_or t:$reduce_and t:$reduce_xor t:$reduce_bool t:$logic_not', 'opt_clean', `write_json ${quote(netlist)}`].join('\n'));
  const run = cp.spawnSync('yosys', ['-Q','-T','-s',yosysScript], {encoding:'utf8', maxBuffer:20*1024*1024});
  if (run.status !== 0) fail(`Yosys failed:\n${(run.stderr+'\n'+run.stdout).split('\n').slice(-25).join('\n')}`);
  if (/Warning:.*(undriven|multiple conflicting drivers)/i.test(run.stdout)) fail('Yosys reported undriven or conflicting signals');
  const yosys = JSON.parse(fs.readFileSync(netlist,'utf8'));
  const top = yosys.modules[req.top];
  if (!top) fail(`Yosys did not retain top ${req.top}`);
  const graph = yosys2digitaljs(yosys);
  for (const [name, mod] of Object.entries(yosys.modules)) {
    if (mod.attributes && mod.attributes.blackbox && Number.parseInt(mod.attributes.blackbox,2))
      fail(`unsupported blackbox module ${name}`);
    const converted = name === req.top ? graph : graph.subcircuits[name];
    if (!converted) fail(`module ${name} was lost during conversion`);
    const labels = new Set(Object.values(converted.devices).map(d=>d.label));
    for (const cell of Object.keys(mod.cells || {}))
      if (!labels.has(cell)) fail(`module ${name}: unsupported or lost cell ${cell}`);
  }
  // Converter 0.10.3 omits WR_EN for asynchronous memories. Recover the
  // whole-word enable from the authoritative Yosys netlist, then constrain
  // this native RAM mapping to a proven shared-address port.
  for(const [name,mod] of Object.entries(yosys.modules)){
    const converted=name===req.top?graph:graph.subcircuits[name];
    for(const [id,dev] of Object.entries(converted.devices))if(dev.type==='Memory'){
      const cell=mod.cells[dev.label], c=cell.connections;
      if(dev.wrports.length!==1 || dev.rdports.length!==1 || dev.wrports[0].clock_polarity!==undefined)continue;
      const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
      if(!c.WR_EN.every(v=>v===c.WR_EN[0]))fail(`memory ${dev.label}: per-bit writes are unsupported`);
      const addrMux=Object.values(mod.cells).find(v=>v.type==='$mux' && equal(v.connections.Y,c.WR_ADDR));
      const enMux=Object.values(mod.cells).find(v=>v.type==='$mux' && v.connections.Y[0]===c.WR_EN[0]);
      dev.cvgenSharedAddress=equal(c.RD_ADDR,c.WR_ADDR) || !!(addrMux && enMux &&
        equal(addrMux.connections.B,c.RD_ADDR) && equal(addrMux.connections.S,enMux.connections.S) &&
        equal(enMux.connections.A,['0']) && equal(enMux.connections.B,['1']));
      dev.wrports[0].no_bit_enable=true;
      let source;
      if(typeof c.WR_EN[0]==='string'){
        const constantId=`cvgen_mem_en_${id}`;
        converted.devices[constantId]={type:'Constant',constant:c.WR_EN[0]};source={id:constantId,port:'out'};
      }else{
        const entry=Object.entries(mod.cells).find(([,v])=>Object.entries(v.port_directions).some(([port,dir])=>
          dir==='output' && equal(v.connections[port],[c.WR_EN[0]])));
        if(entry){const found=Object.entries(converted.devices).find(([,v])=>v.label===entry[0]);
          if(found)source={id:found[0],port:'out'};}
        if(!source){const port=Object.entries(mod.ports).find(([,v])=>v.direction==='input'&&equal(v.bits,[c.WR_EN[0]]));
          if(port){const found=Object.entries(converted.devices).find(([,v])=>v.type==='Input'&&v.net===port[0]);
            if(found)source={id:found[0],port:'out'};}}
      }
      if(!source)fail(`memory ${dev.label}: cannot map asynchronous write enable`);
      if(!converted.connectors.some(v=>v.to.id===id && v.to.port==='wr0en'))
        converted.connectors.push({from:source,to:{id,port:'wr0en'}});
    }
  }
  // Both pinned importers implement Gt as Lt and Le as Ge without reversing
  // operands. Emit equivalent supported primitives so the saved project also
  // behaves correctly in an unpatched CircuitVerse simulator.
  for(const mod of modules(graph))for(const [id,dev] of Object.entries(mod.devices)){
    if(dev.type!=='Gt' && dev.type!=='Le')continue;
    dev.type=dev.type==='Gt'?'Lt':'Ge';
    [dev.bits.in1,dev.bits.in2]=[dev.bits.in2,dev.bits.in1];
    if(dev.signed)[dev.signed.in1,dev.signed.in2]=[dev.signed.in2,dev.signed.in1];
    for(const edge of mod.connectors)if(edge.to.id===id){
      if(edge.to.port==='in1')edge.to.port='in2';
      else if(edge.to.port==='in2')edge.to.port='in1';
    }
  }
  graph.name = req.top;
  const aliases = {};
  Object.keys(graph.subcircuits || {}).forEach((name,i) => {
    if (!/^[A-Za-z_][A-Za-z_0-9]*$/.test(name)) {
      const base = name.match(/\\([A-Za-z_][A-Za-z_0-9]*)/)?.[1] || 'module';
      aliases[name] = `${base}_${i+1}`;
    }
  });
  for (const [original, safe] of Object.entries(aliases)) {
    graph.subcircuits[safe] = graph.subcircuits[original];
    delete graph.subcircuits[original];
  }
  for (const mod of modules(graph)) for (const dev of Object.values(mod.devices)) {
    if (dev.type === 'Subcircuit' && aliases[dev.celltype]) dev.celltype = aliases[dev.celltype];
  }
  // Renaming parameterized modules can move their definitions after users.
  // Native importers need children created before a parent instantiates them.
  const definitions=graph.subcircuits||{}, ordered={}, visiting=new Set();
  function visit(name){
    if(ordered[name])return;
    if(visiting.has(name))fail(`recursive module hierarchy at ${name}`);
    const mod=definitions[name];
    if(!mod)fail(`unknown subcircuit ${name}`);
    visiting.add(name);
    for(const dev of Object.values(mod.devices))if(dev.type==='Subcircuit')visit(dev.celltype);
    visiting.delete(name);ordered[name]=mod;
  }
  Object.keys(definitions).forEach(visit);
  graph.subcircuits=ordered;
  validate(graph, top.ports, req.clocks);
  const graphPath = path.join(scratch, 'graph.json');
  fs.writeFileSync(graphPath, JSON.stringify(graph));
  let engine, runner, command, env;
  if (req.format === 'legacy') {
    engine = process.env.CVGEN_ENGINE_DIR || path.join(os.homedir(), '.cache','cv-gen','engine','6f725c5a924dc0b73527215eb5aa0618e45330e1');
    const jest = path.join(engine,'node_modules','.bin','jest');
    if (!fs.existsSync(jest)) fail(`legacy CircuitVerse engine is missing at ${engine}; run cv-gen engine install`);
    runner = path.join(engine,'simulator','spec','cv-gen-verilog.spec.js');
    fs.copyFileSync(path.join(__dirname,'schematic.cjs'),path.join(path.dirname(runner),'cv-gen-schematic.cjs'));
    fs.copyFileSync(path.join(__dirname,'memory.cjs'),path.join(path.dirname(runner),'cv-gen-memory.cjs'));
    fs.copyFileSync(path.join(__dirname,'legacy.spec.js'),runner);
    command = [jest,`simulator/spec/${path.basename(runner)}`,'--ci','--silent','--runInBand'];
    env={...process.env,CVGEN_GRAPH:graphPath,CVGEN_PROJECT:req.output,CVGEN_CLOCKS:JSON.stringify(req.clocks)};
  } else if (req.format === 'canonical-v1') {
    engine = process.env.CVGEN_V1_DIR || path.join(os.homedir(), '.cache','cv-gen','v1','efadf7a9fda9ff3bf93002e0020bd4a9ba53e920');
    const vitest=path.join(engine,'node_modules','.bin','vitest');
    if (!fs.existsSync(vitest)) fail(`Vue v1 CircuitVerse engine is missing at ${engine}; run cv-gen engine install`);
    runner=path.join(engine,'v1','src','simulator','spec','cv-gen-verilog.spec.js');
    fs.copyFileSync(path.join(__dirname,'schematic.cjs'),path.join(path.dirname(runner),'cv-gen-schematic.cjs'));
    fs.copyFileSync(path.join(__dirname,'memory.cjs'),path.join(path.dirname(runner),'cv-gen-memory.cjs'));
    fs.copyFileSync(path.join(__dirname,'canonical.spec.js'),runner);
    command=[vitest,'run','--project','v1','v1/src/simulator/spec/cv-gen-verilog.spec.js','--reporter=dot'];
    const major=Number(process.versions.node.split('.')[0]);
    env={...process.env,CVGEN_GRAPH:graphPath,CVGEN_PROJECT:req.output,CVGEN_CLOCKS:JSON.stringify(req.clocks)};
    if(major>=25)env.NODE_OPTIONS=`${env.NODE_OPTIONS||''} --localstorage-file=${path.join(scratch,'localstorage.json')}`.trim();
  } else fail(`unsupported format ${req.format}`);
  const adapter = cp.spawnSync(command[0],command.slice(1),{cwd:engine,encoding:'utf8',env,maxBuffer:20*1024*1024});
  if (adapter.status !== 0 || !fs.existsSync(req.output)) fail(`CircuitVerse adapter failed:\n${(adapter.stderr+'\n'+adapter.stdout).split('\n').slice(0,65).join('\n')}`);
}
try { main(); } catch (error) { console.error(error.stack || String(error)); process.exit(1); }
