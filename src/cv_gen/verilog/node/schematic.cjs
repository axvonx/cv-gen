/** CircuitVerse schematic placement and rectilinear net routing.
 * No HDL logic lives here: this operates on native circuit elements and pins.
 * All segments are axis aligned. Foreign pins, bends, and overlapping wire
 * segments are obstacles; straight perpendicular wire crossings are allowed.
 */
const GRID = 10;
const snap = value => Math.ceil(value / GRID) * GRID;
const pointKey = (x, y) => `${x},${y}`;

function elements(scope, kinds) {
  return kinds.flatMap(kind => (scope[kind] || []).map((element, index) => ({
    element, key: `${kind}:${index}`, kind,
  }))).filter(({element}) => element.nodeList?.length);
}

function netsOf(scope) {
  const seen = new Set(), nets = [];
  for (const pin of scope.allNodes) {
    if (seen.has(pin)) continue;
    const stack = [pin], members = [];
    while (stack.length) {
      const node = stack.pop();
      if (seen.has(node) || node.scope !== scope) continue;
      seen.add(node); members.push(node);
      stack.push(...node.connections);
    }
    nets.push(members);
  }
  return nets;
}

// Pin identities survive serialization and native loader reconstruction.
function signature(scope, kinds) {
  const keys = new Map();
  for (const {element, key} of elements(scope, kinds)) {
    for (const [name, value] of Object.entries(element)) {
      if (name === 'nodeList' || name === 'connections') continue;
      const pins = Array.isArray(value) ? value : [value];
      pins.forEach((node, i) => {
        if (node?.objectType === 'Node' && node.parent === element && !keys.has(node)) {
          keys.set(node, `${key}.${name}${Array.isArray(value) ? `[${i}]` : ''}`);
        }
      });
    }
  }
  return netsOf(scope).map(net => net.map(pin => keys.get(pin)).filter(Boolean).sort().join('|'))
    .filter(Boolean).sort();
}

function dimensions(element) {
  const nodes = element.nodeList;
  const x = nodes.map(n => n.absX() - element.x), y = nodes.map(n => n.absY() - element.y);
  let left = Math.min(-element.leftDimensionX || 0, ...x);
  let right = Math.max(element.rightDimensionX || 0, ...x);
  const top = Math.min(-element.upDimensionY || 0, ...y);
  const bottom = Math.max(element.downDimensionY || 0, ...y);
  // Labels need room too, particularly multi-bit Input/Output readouts.
  if (element.label) {
    if (element.labelDirection === 'LEFT') left -= Math.min(150, element.label.length * 7 + 10);
    else if (element.labelDirection === 'RIGHT') right += Math.min(150, element.label.length * 7 + 10);
  }
  return {left, right, top, bottom};
}

function place(scope, kinds, spacing = 1) {
  const items = elements(scope, kinds);
  const owners = new Map();
  items.forEach((item, i) => {
    item.index = i; item.bounds = dimensions(item.element);
    for (const node of item.element.nodeList) owners.set(node, i);
  });
  const predecessors = items.map(() => new Set()), successors = items.map(() => new Set());
  // CircuitVerse Splitter pins are bidirectional (all type 0). Recover their
  // presentation direction from converter port roles and attached drivers.
  for(let pass=0;pass<items.length;pass++){
    let changed=false;
    for(const {element,kind} of items){
      if(kind!=='Splitter')continue;
      const bus=element.inp1, parts=element.outputs;
      const driven=node=>node.connections.some(peer=>peer.parent!==element&&(peer.type===1||peer.cvgenFlowOut));
      let sources=[];
      if(bus.cvgenFlowOut||parts.some(pin=>pin.cvgenFlowIn))sources=[bus];
      else if(bus.cvgenFlowIn||parts.some(pin=>pin.cvgenFlowOut))sources=parts;
      else if(driven(bus))sources=parts;
      else if(parts.some(driven))sources=[bus];
      for(const source of sources)if(!source.cvgenFlowOut){source.cvgenFlowOut=true;changed=true;}
    }
    if(!changed)break;
  }
  for(const item of items){
    const {element,kind}=item;
    // Native ConstantVal renders one character per bit. Its importer defaults
    // undefined/don't-care constants to a one-character zero at any bus width.
    if(kind==='ConstantVal' && typeof element.state==='string' && /^[01]+$/.test(element.state)){
      element.state=element.state.padStart(element.bitWidth,'0');
      element.setDimensions?.(10*element.bitWidth,10);
    }
    item.bounds=dimensions(element);
  }
  for (const net of netsOf(scope)) {
    const sources = net.filter(n => n.type === 1 || n.cvgenFlowOut);
    for (const source of sources) for (const target of net) {
      const a = owners.get(source), b = owners.get(target);
      if (a === undefined || b === undefined || a === b || target.type === 1 || target.cvgenFlowOut) continue;
      // Register feedback is routed physically but cut for left-to-right ranking.
      if (/flipflop|latch|register|ram/i.test(items[b].kind)) continue;
      successors[a].add(b); predecessors[b].add(a);
    }
  }
  // Tarjan SCC condensation also handles combinational feedback deterministically.
  let next = 0;
  const stack = [], active = new Set(), index = [], low = [], groups = [];
  const visit = v => {
    index[v] = low[v] = next++; stack.push(v); active.add(v);
    for (const w of successors[v]) {
      if (index[w] === undefined) { visit(w); low[v] = Math.min(low[v], low[w]); }
      else if (active.has(w)) low[v] = Math.min(low[v], index[w]);
    }
    if (low[v] === index[v]) {
      const group = []; let w;
      do { w = stack.pop(); active.delete(w); group.push(w); } while (w !== v);
      groups.push(group);
    }
  };
  items.forEach((_, i) => { if (index[i] === undefined) visit(i); });
  const groupOf = [];
  groups.forEach((group, i) => group.forEach(v => { groupOf[v] = i; }));
  const ranks = [], ranking = new Set();
  const rank = g => {
    if (ranks[g] !== undefined) return ranks[g];
    if (ranking.has(g)) throw Error('schematic ranking cycle');
    ranking.add(g); let result = 0;
    for (const v of groups[g]) for (const p of predecessors[v]) {
      if (groupOf[p] !== g) result = Math.max(result, rank(groupOf[p]) + 1);
    }
    ranking.delete(g); return ranks[g] = result;
  };
  groups.forEach((_, g) => rank(g));
  items.forEach((item, i) => { item.rank = ranks[groupOf[i]]; });
  const finalRank = Math.max(0, ...items.filter(v => v.kind !== 'Output').map(v => v.rank)) + 1;
  items.filter(v => v.kind === 'Output').forEach(v => { v.rank = finalRank; });
  const constants = items.filter(v => v.kind === 'ConstantVal' && successors[v.index].size);
  const sidecars = new Set(constants);
  const layers = Array.from({length: 1 + Math.max(0, ...items.map(v => v.rank))}, () => []);
  items.filter(v => !sidecars.has(v)).forEach(item => layers[item.rank].push(item));
  let order = new Map();
  const refresh = () => layers.forEach(layer => layer.forEach((item, i) => order.set(item.index, i)));
  refresh();
  // Alternating barycenter sweeps bring connected blocks into matching rows.
  for (let sweep = 0; sweep < 8; sweep++) {
    const forward = sweep % 2 === 0;
    for (const layer of forward ? layers : [...layers].reverse()) {
      const score = item => {
        const adjacent = [...(forward ? predecessors[item.index] : successors[item.index])].filter(v => order.has(v));
        return adjacent.length ? adjacent.reduce((sum, v) => sum + order.get(v), 0) / adjacent.length
          : order.get(item.index);
      };
      layer.sort((a, b) => score(a) - score(b) || a.index - b.index); refresh();
    }
  }
  let columnX = 300;
  const height = layer => layer.reduce((sum,v) => sum + v.bounds.bottom-v.bounds.top+90*spacing,0);
  const totalHeight = Math.max(100,...layers.map(height));
  for (const [layerIndex,layer] of layers.entries()) {
    const columnWidth = snap(Math.max(80, ...layer.map(v => v.bounds.right - v.bounds.left)));
    let cursor = snap(100 + (totalHeight-height(layer))/2);
    layer.forEach(item => {
      const {element,bounds} = item;
      element.x = snap(columnX-bounds.left);
      element.y = snap(cursor-bounds.top);
      cursor += snap(bounds.bottom-bounds.top+90*spacing);
    });
    const reach=group=>Math.max(30,...group.map(v=>{
      const counts=new Map();for(const pin of v.element.nodeList)counts.set(pin.absX(),(counts.get(pin.absX())||0)+1);
      return Math.max(...counts.values())>2?Math.max(...counts.values())*20+30:30;
    }));
    columnX += columnWidth + Math.max(240,reach(layer)+reach(layers[layerIndex+1]||[])+100)*spacing;
  }
  const occupied = items.filter(v=>!sidecars.has(v));
  const overlaps = (a,b) => a.element.x+a.bounds.left-30 < b.element.x+b.bounds.right &&
    a.element.x+a.bounds.right+30 > b.element.x+b.bounds.left &&
    a.element.y+a.bounds.top-30 < b.element.y+b.bounds.bottom &&
    a.element.y+a.bounds.bottom+30 > b.element.y+b.bounds.top;
  for(const item of constants){
    const consumer=items[[...successors[item.index]].sort((a,b)=>items[a].rank-items[b].rank||a-b)[0]];
    const target=item.element.nodeList.flatMap(pin=>pin.connections).find(pin=>pin.parent===consumer.element);
    // Keep sidecars outside the full fan of staggered access lanes, not only
    // outside the component body. Otherwise a dense input can be fenced in.
    const parallel=target?consumer.element.nodeList.filter(pin=>pin.absX()===target.absX()).length:0;
    const reach=parallel>2?parallel*20:0;
    item.element.x=snap(consumer.element.x+consumer.bounds.left-70-item.bounds.right-reach);
    const center=target?target.absY():consumer.element.y;
    for(let attempt=0;;attempt++){
      const offset=attempt===0?0:Math.ceil(attempt/2)*70*(attempt%2?1:-1);
      item.element.y=snap(Math.max(60-item.bounds.top,center+offset));
      if(!occupied.some(other=>overlaps(item,other)))break;
      if(attempt>1000)throw Error('cannot place constant beside its consumer');
    }
    occupied.push(item);
  }
  return items;
}

class Heap {
  constructor() { this.data = []; }
  push(value) {
    const a = this.data; a.push(value); let i = a.length - 1;
    while (i) { const p = (i - 1) >> 1; if (a[p][0] <= value[0]) break; a[i] = a[p]; i = p; }
    a[i] = value;
  }
  pop() {
    const a = this.data, first = a[0], last = a.pop();
    if (a.length) {
      let i = 0;
      while (i * 2 + 1 < a.length) {
        let c = i * 2 + 1;
        if (c + 1 < a.length && a[c + 1][0] < a[c][0]) c++;
        if (a[c][0] >= last[0]) break;
        a[i] = a[c]; i = c;
      }
      a[i] = last;
    }
    return first;
  }
}

function routeOnce(scope, kinds, Node, options = {}) {
  const before = signature(scope, kinds);
  const items = options.place === false
    ? elements(scope,kinds).map(item => ({...item,bounds:dimensions(item.element)}))
    : place(scope, kinds, options.spacing || 1);
  const original = scope.allNodes.slice();
  if (original.some(n => n.type === 2)) throw Error('route schematic before adding wire bends');
  const nets = netsOf(scope).filter(net => net.length > 1);
  const boxes = new Map(items.map(({element, bounds}) => [element, {
    l: element.x + bounds.left, r: element.x + bounds.right,
    t: element.y + bounds.top, b: element.y + bounds.bottom,
  }]));
  const maxX = Math.max(300, ...[...boxes.values()].map(b => b.r));
  const maxY = Math.max(300, ...[...boxes.values()].map(b => b.b));
  const cols = Math.ceil(maxX / GRID) + 25, rows = Math.ceil(maxY / GRID) + 25;
  const size = cols * rows;
  if(size>8000000)throw Error(`schematic ${scope.name}: ${items.length} elements need grid ${cols}x${rows}; split this module into smaller modules`);
  const blocked = new Uint8Array(size);
  const horizontal = new Int32Array(size), vertical = new Int32Array(size), points = new Int32Array(size);
  const cell = (x, y) => {
    if (Math.abs(x / GRID - Math.round(x / GRID)) > 1e-6 || Math.abs(y / GRID - Math.round(y / GRID)) > 1e-6) {
      throw Error(`pin is off the ${GRID}-unit schematic grid: ${x},${y}`);
    }
    return Math.round(y / GRID) * cols + Math.round(x / GRID);
  };
  const xy = id => [id % cols * GRID, Math.floor(id / cols) * GRID];
  for (const box of boxes.values()) {
    for (let y = Math.floor(box.t / GRID); y <= Math.ceil(box.b / GRID); y++) {
      for (let x = Math.floor(box.l / GRID); x <= Math.ceil(box.r / GRID); x++) blocked[y * cols + x] = 1;
    }
  }
  const netIds = new Map();
  nets.forEach((net, i) => net.forEach(pin => netIds.set(pin, i + 1)));
  for (const pin of original) {
    const p = cell(pin.absX(), pin.absY());
    const owner = netIds.get(pin) || -1;
    if (points[p] && points[p] !== owner) throw Error('overlapping schematic pins');
    points[p] = owner;
  }
  const graph = nets.map(() => new Map()), escapes = new Map();
  const join = (g, a, b) => {
    if (!g.has(a)) g.set(a, new Set());
    if (!g.has(b)) g.set(b, new Set());
    g.get(a).add(b); g.get(b).add(a);
  };
  const addPath = (path, id) => {
    const g = graph[id - 1];
    for (let i = 1; i < path.length; i++) {
      const a = path[i - 1], b = path[i], h = Math.floor(a / cols) === Math.floor(b / cols);
      const occupied = h ? horizontal : vertical;
      for (const p of [a, b]) {
        if (occupied[p] && occupied[p] !== id) throw Error(`overlapping nets in schematic route ${scope.name} at ${xy(p)}: ${id} and ${occupied[p]}`);
        occupied[p] = id;
      }
      join(g, a, b);
    }
    for (const p of path) {
      const peers = [...g.get(p) || []];
      if (peers.length !== 2 || Math.abs(peers[0] - peers[1]) !== 2 && Math.abs(peers[0] - peers[1]) !== cols * 2) {
        if (points[p] && points[p] !== id) throw Error('schematic junction touches another net');
        points[p] = id;
      }
    }
  };
  const line = (a, b) => {
    const step = a % cols === b % cols ? (b > a ? cols : -cols) : (b > a ? 1 : -1);
    const result = [a]; while (a !== b) { a += step; result.push(a); } return result;
  };
  // Reserve short pin exits before routing so every control gets its own access.
  nets.forEach((net, i) => net.forEach(pin => {
    const box = boxes.get(pin.parent), x = pin.absX(), y = pin.absY();
    const nodeXs = pin.parent.nodeList.map(n => n.absX()), nodeYs = pin.parent.nodeList.map(n => n.absY());
    let end;
    if (y === Math.max(...nodeYs) && y >= pin.parent.y && x > Math.min(...nodeXs) && x < Math.max(...nodeXs)) {
      end = [x, snap(box.b + 30)];
    } else if (y === Math.min(...nodeYs) && y < pin.parent.y && x > Math.min(...nodeXs) && x < Math.max(...nodeXs)) {
      end = [x, Math.floor((box.t - 30) / GRID) * GRID];
    } else if (x === Math.min(...nodeXs) && (pin.type === 0 || x < pin.parent.x)) {
      end = [Math.floor((box.l - 30) / GRID) * GRID, y];
    } else {
      end = [snap(box.r + 30), y];
    }
    // Dense reduction gates and splitters have pins one grid unit apart.
    // Stagger their access lanes so earlier routes cannot fence in a middle pin.
    const parallelPins=pin.parent.nodeList.filter(n=>n.absX()===x).sort((a,b)=>a.absY()-b.absY());
    if(parallelPins.length>2 && end[1]===y){
      const extra=parallelPins.indexOf(pin)*20;
      end[0]+=end[0]<x?-extra:extra;
    }
    const start = cell(x, y), target = cell(...end);
    escapes.set(pin, target);
    addPath(line(start, target), i + 1);
    points[target] = i + 1;
  }));
  const search = (start, targets, id) => {
    const tx = [...targets].map(p => p % cols), ty = [...targets].map(p => Math.floor(p / cols));
    const l = Math.min(...tx), r = Math.max(...tx), t = Math.min(...ty), b = Math.max(...ty);
    const heuristic = p => {
      const x = p % cols, y = Math.floor(p / cols);
      return Math.max(0, l - x, x - r) + Math.max(0, t - y, y - b);
    };
    const distance = new Float64Array(size * 3); distance.fill(Infinity);
    const previous = new Int32Array(size * 3); previous.fill(-1);
    const heap = new Heap(), initial = start * 3;
    distance[initial] = 0; heap.push([heuristic(start), initial, 0]);
    while (heap.data.length) {
      const [, state, cost] = heap.pop();
      if (cost !== distance[state]) continue;
      const p = Math.floor(state / 3), direction = state % 3;
      if (targets.has(p)) {
        const path = []; let s = state;
        while (s !== -1) { path.push(Math.floor(s / 3)); s = previous[s]; }
        return path.reverse();
      }
      const x = p % cols, y = Math.floor(p / cols);
      for (const [q, axis] of [[x + 1 < cols ? p + 1 : -1,1],[x > 0 ? p - 1 : -1,1],
        [y + 1 < rows ? p + cols : -1,2],[y > 0 ? p - cols : -1,2]]) {
        if (q < 0 || blocked[q] || points[q] && points[q] !== id) continue;
        const parallel = axis === 1 ? horizontal : vertical;
        const perpendicular = axis === 1 ? vertical : horizontal;
        if (parallel[q] && parallel[q] !== id || parallel[p] && parallel[p] !== id) continue;
        // A bend on a foreign wire becomes an electrical junction in CircuitVerse.
        if (direction && direction !== axis && (horizontal[p] && horizontal[p] !== id || vertical[p] && vertical[p] !== id)) continue;
        const crossing = perpendicular[q] && perpendicular[q] !== id;
        const nextCost = cost + 1 + (direction && direction !== axis ? 5 : 0) + (crossing ? 12 : 0);
        const next = q * 3 + axis;
        if (nextCost < distance[next]) {
          distance[next] = nextCost; previous[next] = state;
          heap.push([nextCost + heuristic(q), next, nextCost]);
        }
      }
    }
    throw Error(`no clear wire route for ${scope.name} net ${id}; pins ${nets[id-1].map(pin=>`${pin.parent.objectType}@${pin.absX()},${pin.absY()}`).join('; ')}`);
  };
  const jobs = nets.map((pins, i) => ({pins, id:i + 1})).sort((a,b) => b.pins.length - a.pins.length || a.id - b.id);
  for (const {pins, id} of jobs) {
    const root = pins.find(pin => pin.type === 1 || pin.cvgenFlowOut) || pins[0];
    const tree = new Set(line(cell(root.absX(),root.absY()), escapes.get(root)));
    const pending = pins.filter(pin => pin !== root).sort((a,b) => {
      const ax = a.absX()-root.absX(), ay = a.absY()-root.absY();
      const bx = b.absX()-root.absX(), by = b.absY()-root.absY();
      return Math.abs(ax)+Math.abs(ay)-Math.abs(bx)-Math.abs(by);
    });
    for (const pin of pending) {
      const end = escapes.get(pin);
      const path = search(end, tree, id);
      addPath(path, id);
      for (const p of path) tree.add(p);
      for (const p of line(cell(pin.absX(),pin.absY()),end)) tree.add(p);
    }
  }
  // Replace graph-only importer connections with compressed physical wire trees.
  for (const node of original) for (const peer of node.connections.slice()) node.disconnectWireLess(peer);
  let length = 0, bends = 0, segments = 0;
  nets.forEach((pins, i) => {
    const g = graph[i], vertices = new Map();
    for (const pin of pins) {
      const p = cell(pin.absX(),pin.absY());
      if (vertices.has(p)) vertices.get(p).connectWireLess(pin);
      else vertices.set(p,pin);
    }
    for (const [p, peers] of g) {
      const neighbors = [...peers];
      const straight = neighbors.length === 2 && (Math.abs(neighbors[0]-neighbors[1]) === 2 || Math.abs(neighbors[0]-neighbors[1]) === cols*2);
      if (!straight && !vertices.has(p)) {
        const [x,y] = xy(p); vertices.set(p,new Node(x,y,2,scope.root,pins[0].bitWidth)); bends++;
      }
    }
    const visited = new Set();
    for (const [p, node] of vertices) for (const neighbor of g.get(p) || []) {
      const edge = (a,b) => a < b ? `${a}:${b}` : `${b}:${a}`;
      if (visited.has(edge(p,neighbor))) continue;
      let previous = p, next = neighbor, units = 1; visited.add(edge(p,neighbor));
      while (!vertices.has(next)) {
        if(units>g.size)throw Error(`wire compression cycle in ${scope.name} net ${i+1}`);
        const following = [...g.get(next)].find(v => v !== previous);
        visited.add(edge(next,following)); previous = next; next = following; units++;
      }
      node.connectWireLess(vertices.get(next)); length += units * GRID; segments++;
    }
  });
  if (JSON.stringify(signature(scope,kinds)) !== JSON.stringify(before)) throw Error(`schematic routing changed ${scope.name} pin connectivity`);
  return {elements:items.length,nets:nets.length,segments,bends,length,width:maxX,height:maxY};
}

function route(scope,kinds,Node,options={}){
  if(options.place===false)return routeOnce(scope,kinds,Node,options);
  for(const spacing of [1,1.5,2.25]){
    try{return routeOnce(scope,kinds,Node,{...options,spacing:(options.spacing||1)*spacing});}
    catch(error){if(!/^(no clear wire route|overlapping nets in schematic route|schematic junction touches)/.test(error.message) || spacing===2.25)throw error;}
  }
}
module.exports = {GRID, place, route, signature};
