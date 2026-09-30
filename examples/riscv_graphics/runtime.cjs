const {performance}=require('node:perf_hooks');
module.exports.execute=function(scope,play,errorDetectedGet,errorDetectedSet,request){
 const inputs=Object.fromEntries(scope.Input.map(p=>[p.label,p]));
 const outputs=Object.fromEntries(scope.Output.map(p=>[p.label,p]));
 function step(values){
  for(const [name,value] of Object.entries(values))inputs[name].state=value;
  play(scope);
  if(errorDetectedGet())throw Error('native CircuitVerse engine error');
 }
 function read(name){
  const value=outputs[name].inp1.value;
  if(value===undefined || !Number.isFinite(value))throw Error(`undriven output ${name}`);
  return value>>>0;
 }
 errorDetectedSet(false);
 step(Object.fromEntries(Object.keys(inputs).map(n=>[n,0])));
 step({rst:1});step({rst:0});
 for(const item of request.loads){
  step({load_address:item.address,load_data:item.data});
  step({load_enable:1});step({load_enable:0});
 }
 step({boot_ram:request.loads.length?1:0,rst:1});step({rst:0});step({run:1});
 const rows=[],fields=request.fields;
 const executionStart=performance.now();
 for(let cycle=1;cycle<=request.limit;cycle++){
  step({clk:1});
  rows.push(Object.fromEntries([['cycle',cycle],...fields.map(name=>[name,read(name)])]));
  step({clk:0});
  if(read('done')||read('fault'))break;
 }
 const executionMs=performance.now()-executionStart;
 if(!read('done') || read('fault'))throw Error(`CPU stopped unsuccessfully at PC ${read('pc')}`);
 const matrix=scope.RGBLedMatrix[0];
 if(!matrix)throw Error("missing live screen");
 for(const pin of [...matrix.rowEnableNodes,...matrix.columnColorNodes]){
  if(pin.value===undefined)throw Error('undefined screen connection');
 }
 const screenColors=matrix.colors.flat().map(v=>v||0);
 step({run:0,inspect:1});
 const pixels=[];
 for(let i=0;i<256;i++){step({peek_address:0xf000+i});pixels.push(read('pixel'));}
 step({peek_address:0xe100});const farWord=read('peek_word');
 step({peek_address:0xfffc});const lastWord=read('peek_word');
 return {rows,pixels,screen_colors:screenColors,far_word:farWord,last_word:lastWord,execution_ms:executionMs};
};
