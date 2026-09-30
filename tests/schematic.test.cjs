const {test} = require('node:test');
const assert = require('node:assert/strict');
const {route,signature} = require('../src/cv_gen/verilog/node/schematic.cjs');

class Node {
  constructor(x,y,type,parent,bitWidth=1){
    Object.assign(this,{x,y,type,parent,bitWidth,scope:parent.scope,objectType:'Node',connections:[]});
    this.scope.allNodes.push(this);
    if(parent.nodeList)parent.nodeList.push(this);
  }
  absX(){return this.parent.x+this.x;}
  absY(){return this.parent.y+this.y;}
  connectWireLess(peer){if(peer===this||this.connections.includes(peer))return;this.connections.push(peer);peer.connections.push(this);}
  disconnectWireLess(peer){this.connections=this.connections.filter(n=>n!==peer);peer.connections=peer.connections.filter(n=>n!==this);}
}
function scope(){const s={name:'fixture',allNodes:[],Gate:[],Input:[],Output:[]};s.root={x:0,y:0,scope:s};return s;}
function gate(s,kind,x,y,width=1){
  const e={objectType:kind,x,y,scope:s,nodeList:[],leftDimensionX:20,rightDimensionX:20,upDimensionY:20,downDimensionY:20};
  s[kind].push(e);
  e.input=new Node(-20,0,0,e,width);e.output=new Node(20,0,1,e,width);return e;
}
function segments(s){return s.allNodes.flatMap((n,i)=>n.connections.filter(p=>s.allNodes.indexOf(p)>i).map(p=>[n,p]));}
const kinds=['Input','Gate','Output'];
function verify(s,before){
  assert.deepEqual(signature(s,kinds),before);
  for(const [a,b] of segments(s)){
    assert.ok(a.absX()===b.absX()||a.absY()===b.absY(),'diagonal wire');
    assert.equal(a.bitWidth,b.bitWidth);
    assert.equal(a.absX()%10,0);assert.equal(a.absY()%10,0);
  }
  // Reproduce native nodeConnect: no unrelated node may land on a segment.
  for(const [a,b] of segments(s))for(const p of s.allNodes){
    if(p===a||p===b)continue;
    const on=a.absX()===b.absX()
      ? p.absX()===a.absX()&&p.absY()>Math.min(a.absY(),b.absY())&&p.absY()<Math.max(a.absY(),b.absY())
      : p.absY()===a.absY()&&p.absX()>Math.min(a.absX(),b.absX())&&p.absX()<Math.max(a.absX(),b.absX());
    if(on){
      const stack=[a],seen=new Set();
      while(stack.length){const n=stack.pop();if(seen.has(n))continue;seen.add(n);stack.push(...n.connections);}
      assert.ok(seen.has(p),'unintended wire junction');
    }
  }
}

test('short obstacle-aware orthogonal route preserves a mixed-width fanout',()=>{
  const s=scope();const a=gate(s,'Input',100,100,8), b=gate(s,'Output',500,100,8), c=gate(s,'Output',500,250,8);
  gate(s,'Gate',300,100);a.output.connectWireLess(b.input);a.output.connectWireLess(c.input);
  const before=signature(s,kinds),report=route(s,kinds,Node,{place:false});verify(s,before);
  assert.ok(report.length<1000);
  for(const [p,q] of segments(s)){
    if(p.absY()===q.absY()&&p.absY()>=80&&p.absY()<=120){
      assert.ok(Math.max(p.absX(),q.absX())<280||Math.min(p.absX(),q.absX())>320,'wire crosses obstacle');
    }
  }
});

test('crossing nets remain independent after native-style junction checks',()=>{
  const s=scope();const a=gate(s,'Input',100,100),b=gate(s,'Output',500,300);
  const c=gate(s,'Input',100,300,4),d=gate(s,'Output',500,100,4);
  a.output.connectWireLess(b.input);c.output.connectWireLess(d.input);
  const before=signature(s,kinds);route(s,kinds,Node,{place:false});verify(s,before);
});

test('placement follows connectivity and is deterministic',()=>{
  const build=()=>{
    const s=scope();const b=gate(s,'Gate',0,0),c=gate(s,'Output',0,0),a=gate(s,'Input',0,0);
    a.output.connectWireLess(b.input);b.output.connectWireLess(c.input);
    const before=signature(s,kinds);route(s,kinds,Node);verify(s,before);
    assert.ok(a.x<b.x&&b.x<c.x);
    return s.allNodes.map(n=>[n.absX(),n.absY(),n.type,n.connections.map(p=>s.allNodes.indexOf(p)).sort((a,b)=>a-b)]);
  };
  assert.deepEqual(build(),build());
});

test('feedback cycles terminate without changing net connectivity',()=>{
  const s=scope();const a=gate(s,'Gate',0,0),b=gate(s,'Gate',0,0);
  a.output.connectWireLess(b.input);b.output.connectWireLess(a.input);
  const before=signature(s,kinds);route(s,kinds,Node);verify(s,before);
});

test('bus constants are padded and placed beside their consumer',()=>{
  const s=scope();s.ConstantVal=[];
  const input=gate(s,'Input',0,0,8),consumer=gate(s,'Gate',0,0,8),output=gate(s,'Output',0,0,8);
  const constant=gate(s,'ConstantVal',0,0,8);
  constant.state='0';constant.bitWidth=8;
  input.output.connectWireLess(consumer.input);
  // Use a separate native input pin for the constant net.
  consumer.operand=new Node(-20,10,0,consumer,8);
  constant.output.connectWireLess(consumer.operand);
  consumer.output.connectWireLess(output.input);
  const extended=[...kinds,'ConstantVal'];
  const before=signature(s,extended);
  route(s,extended,Node);
  assert.deepEqual(signature(s,extended),before);
  assert.equal(constant.state,'00000000');
  assert.ok(constant.x<consumer.x && consumer.x-constant.x<200);
  assert.ok(Math.abs(constant.y-consumer.y)<200);
});

test('constant on a bottom control pin does not overlap the data pin exit',()=>{
  const s=scope();s.ConstantVal=[];
  const source=gate(s,'Input',0,0,4),consumer=gate(s,'Gate',0,0,4);
  consumer.enable=new Node(0,20,0,consumer,1);
  const constant=gate(s,'ConstantVal',0,0,1);constant.state='1';constant.bitWidth=1;
  source.output.connectWireLess(consumer.input);constant.output.connectWireLess(consumer.enable);
  const extended=[...kinds,'ConstantVal'];const before=signature(s,extended);
  route(s,extended,Node);assert.deepEqual(signature(s,extended),before);
  assert.equal(constant.y,consumer.enable.absY());verify(s,signature(s,kinds));
});

test('constant beside a dense block stays beyond all staggered pin exits',()=>{
  const s=scope();s.ConstantVal=[];
  const consumer=gate(s,'Gate',0,0,8);
  const pins=[consumer.input];
  for(let i=1;i<7;i++)pins.push(new Node(-20,i*20,0,consumer,8));
  const constant=gate(s,'ConstantVal',0,0,8);constant.state='0';constant.bitWidth=8;
  pins.forEach((pin,i)=>{
    const source=i===4?constant:gate(s,'Input',0,0,8);
    source.output.connectWireLess(pin);
  });
  const output=gate(s,'Output',0,0,8);consumer.output.connectWireLess(output.input);
  const kinds2=[...kinds,'ConstantVal'];
  const before=signature(s,kinds2);
  route(s,kinds2,Node);
  assert.deepEqual(signature(s,kinds2),before);
});


test('center control pin exits vertically without merging data and output nets',()=>{
 const s=scope();
 const data=gate(s,'Input',0,0,24),enable=gate(s,'Input',0,0,1);
 const buffer=gate(s,'Gate',0,0,24),sink=gate(s,'Output',0,0,24);
 buffer.enable=new Node(0,0,0,buffer,1);
 data.output.connectWireLess(buffer.input);enable.output.connectWireLess(buffer.enable);
 buffer.output.connectWireLess(sink.input);
 const before=signature(s,kinds);route(s,kinds,Node);verify(s,before);
 const peer=buffer.enable.connections[0];
 assert.equal(peer.absX(),buffer.enable.absX());
 assert.ok(peer.absY()>buffer.enable.absY());
});
