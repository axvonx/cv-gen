// Deterministic browser timer/task harness; run with node --test.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('tools/circuitverse-turbo.user.js', 'utf8');
const callback = `function clockTick(...args) {
    if (!simulationArea.clockEnabled || errorDetectedGet() || layoutModeGet()) return;
    globalScope.clockTick(...args); plotArea.nextCycle(); play(); scheduleUpdate(0,20);
}`;
function harness({ late = false, unsupported = false } = {}) {
    let now = 0, next = 1;
    const timers = new Map(), tasks = [], events = {}, frames = [], menus = [];
    const context = {
        console: { error() {} },
        location: { pathname: unsupported ? '/simulatorvue' : '/simulator', search: '' },
        navigator: { userAgent: 'Firefox/144.0' },
        document: { readyState: late ? 'complete' : 'loading', hidden: false,
            addEventListener(type, fn) { events[type] = fn; } },
        performance: { now: () => now },
        setInterval(fn, delay, ...args) { const id = next++; timers.set(id, { fn, delay, args, repeat: true }); return id; },
        setTimeout(fn, delay, ...args) { const id = next++; timers.set(id, { fn, delay, args }); return id; },
        clearInterval(id) { timers.delete(id); }, clearTimeout(id) { timers.delete(id); },
        requestAnimationFrame(fn) { frames.push(fn); },
        GM_registerMenuCommand(label, fn) { menus.push({ label, fn }); },
        MessageChannel: class { constructor() {
            this.port1 = {};
            this.port2 = { postMessage: data => tasks.push(() => this.port1.onmessage({ data })) };
        } },
        simulationArea: { clockEnabled: true }, error: false, layout: false,
        errorDetectedGet() { return context.error; }, layoutModeGet() { return context.layout; },
        plotArea: { nextCycle() {} }, play() {}, scheduleUpdate() {},
    };
    context.window = context; context.top = context;
    vm.createContext(context);
    vm.runInContext(source, context);
    let accepted = 0, cost = 0.1, argsSeen;
    context.globalScope = { Clock: [{}], SubCircuit: [], clockTick(...args) { accepted++; now += cost; argsSeen = args; } };
    vm.runInContext(callback, context);
    const api = context.__circuitVerseTurbo;
    return { context, api, timers, tasks, menus,
        register: (delay = 50, ...args) => context.setInterval(context.clockTick, delay, ...args),
        get accepted() { return accepted; }, get argsSeen() { return argsSeen; },
        cost(value) { cost = value; },
        task() { const fn = tasks.shift(); if (fn) fn(); },
        native(id) { const timer = timers.get(id); timer.fn(...timer.args); if (!timer.repeat) timers.delete(id); },
        poll() { const entry = [...timers].find(([, t]) => !t.repeat && t.delay === 250); assert.ok(entry); this.native(entry[0]); },
        hidden(value) { context.document.hidden = value; events.visibilitychange(); },
        frame(time) { now = time; frames.shift()(now); },
        reloadScript() { vm.runInContext(source, context); },
    };
}
test('normal delay, args and unrelated timers; Turbo restores registered scheduling', () => {
    const h = harness(), unrelated = h.context.setInterval(() => {}, 50);
    const handle = h.register(75, 'arg', 123);
    assert.equal(h.api.snapshot().enabled, false);
    const clock = [...h.timers].find(([, t]) => t.delay === 75)[0];
    h.native(clock); assert.equal(h.accepted, 1); assert.deepEqual(h.argsSeen, ['arg', 123]);
    h.api.setEnabled(true); assert.ok(h.timers.has(unrelated)); assert.ok(!h.timers.has(clock));
    h.task(); assert.ok(h.accepted > 1); assert.equal(h.tasks.length, 1);
    h.api.setEnabled(false); const count = h.accepted; h.task(); assert.equal(h.accepted, count);
    assert.ok([...h.timers.values()].some(t => t.delay === 75));
    h.context.clearInterval(handle);
    assert.equal(h.api.snapshot().registrations, 0);
});
test('recognition fails closed for same-delay and malformed clock callbacks', () => {
    const h = harness();
    h.context.setInterval(function clockTick() {}, 50);
    h.context.setInterval(() => {}, 50);
    h.api.setEnabled(true);
    h.context.document.readyState = 'complete';
    assert.equal(h.api.snapshot().registrations, 0);
    assert.match(h.api.snapshot().status, /not found/);
});
test('both cancellation APIs and replacement invalidate pending work', () => {
    for (const clear of ['clearTimeout', 'clearInterval']) {
        const h = harness(), handle = h.register();
        h.api.setEnabled(true); h.task(); h.context[clear](handle);
        const before = h.accepted; h.task(); assert.equal(h.accepted, before);
        const replacement = h.register(100); assert.notEqual(replacement, handle);
        h.task(); assert.ok(h.accepted > before); assert.equal(h.tasks.length, 1);
        h.context[clear](replacement); h.task(); assert.equal(h.api.snapshot().pending, false);
    }
});
test('duplicate initialization and ambiguous registrations preserve single runner', () => {
    const h = harness(); h.register(); h.api.setEnabled(true);
    const hook = h.context.setInterval; h.reloadScript(); assert.equal(h.context.setInterval, hook);
    assert.equal(h.menus.length, 2); assert.equal(h.tasks.length, 1);
    const second = h.register(); assert.equal(h.api.snapshot().enabled, false);
    assert.match(h.api.snapshot().status, /ambiguous/); h.task(); assert.equal(h.accepted, 0);
    assert.equal([...h.timers.values()].filter(t => t.delay === 50).length, 2);
    h.context.clearInterval(second); h.api.setEnabled(true); h.task(); assert.ok(h.accepted > 0);
});
test('pause, error, layout, loading and no-clock suspend to polling and resume', () => {
    for (const state of ['pause', 'error', 'layout', 'loading', 'empty']) {
        const h = harness(); h.register(); h.api.setEnabled(true);
        if (state === 'pause') h.context.simulationArea.clockEnabled = false;
        if (state === 'error') h.context.error = true;
        if (state === 'layout') h.context.layout = true;
        if (state === 'loading') h.context.loading = true;
        if (state === 'empty') h.context.globalScope.Clock = [];
        h.task(); assert.equal(h.accepted, 0); assert.equal(h.tasks.length, 0);
        assert.ok(h.api.snapshot().polling);
        h.context.simulationArea.clockEnabled = true; h.context.error = h.context.layout = h.context.loading = false;
        h.context.globalScope.Clock = [{}]; h.poll(); h.task(); assert.ok(h.accepted > 0);
    }
});
test('hidden tab cancels pumping and polling, resumes without catch-up', () => {
    const h = harness(); h.register(); h.api.setEnabled(true); h.task();
    h.hidden(true); const count = h.accepted; h.task();
    assert.equal(h.accepted, count); assert.equal(h.tasks.length, 0);
    assert.equal([...h.timers.values()].filter(t => t.delay === 50 || t.delay === 250).length, 0);
    assert.match(h.api.snapshot().status, /hidden/);
    h.frame(100000); h.hidden(false); h.task();
    assert.ok(h.accepted - count <= 256); assert.equal(h.api.snapshot().maxFrameGapMs, 0);
});
test('descriptor restored exactly, including inherited clockTick, and circuit switches followed', () => {
    const h = harness(); h.register();
    const original = Object.getOwnPropertyDescriptor(h.context.globalScope, 'clockTick');
    h.api.setEnabled(true); h.task();
    assert.deepEqual(Object.getOwnPropertyDescriptor(h.context.globalScope, 'clockTick'), original);
    let switched = 0;
    const proto = { clockTick() { switched++; } };
    h.context.globalScope = Object.assign(Object.create(proto), { Clock: [], SubCircuit: [{localScope:{Clock:[{}]}}] });
    h.task(); assert.ok(switched > 0); assert.ok(!Object.hasOwn(h.context.globalScope, 'clockTick'));
});
test('exceptions restore descriptor and native timing; slow tick ends batch', () => {
    const h = harness(); h.register(); h.cost(150); h.api.setEnabled(true); h.task();
    assert.equal(h.accepted, 1); assert.match(h.api.snapshot().status, /Slow/);
    const throwing = () => { throw Error('tick failure'); };
    h.context.globalScope.clockTick = throwing; h.task();
    assert.equal(h.context.globalScope.clockTick, throwing);
    assert.equal(h.api.snapshot().enabled, false); assert.match(h.api.snapshot().status, /tick failure/);
    assert.ok([...h.timers.values()].some(t => t.delay === 50));
});
test('adaptive budget shrinks for repeated gaps and recovers after sustained smooth frames', () => {
    const h = harness(); h.register(); h.api.setEnabled(true);
    h.frame(0); h.frame(101); h.frame(202); assert.equal(h.api.snapshot().budgetMs, 4);
    h.frame(303); h.frame(404); assert.equal(h.api.snapshot().budgetMs, 2);
    for (let i=1;i<=720;i++) h.frame(404+i*16);
    assert.equal(h.api.snapshot().budgetMs, 8);
});
test('late injection and unsupported routes never replace timers', () => {
    for (const options of [{late:true}, {unsupported:true}]) {
        const h = harness(options); const id = h.register();
        assert.ok(id > 0); h.api.setEnabled(true); assert.equal(h.api.snapshot().enabled, false);
        assert.match(h.api.snapshot().status, /Reload required|Unsupported/);
    }
});
test('zero-cost callbacks cap each task at 256 and retain args in Turbo', () => {
    const h = harness(); h.cost(0); h.register(50, 'turbo-arg'); h.api.setEnabled(true); h.task();
    assert.equal(h.accepted, 256); assert.deepEqual(h.argsSeen, ['turbo-arg']);
    h.task(); assert.equal(h.accepted, 512); assert.equal(h.tasks.length, 1);
});
test('non-writable scope observation fails closed without changing the descriptor', () => {
    const h = harness(); h.register();
    Object.defineProperty(h.context.globalScope, 'clockTick', {writable:false, configurable:false});
    const descriptor=Object.getOwnPropertyDescriptor(h.context.globalScope,'clockTick');
    h.api.setEnabled(true); h.task();
    assert.equal(h.accepted, 0); assert.equal(h.api.snapshot().enabled, false);
    assert.deepEqual(Object.getOwnPropertyDescriptor(h.context.globalScope,'clockTick'),descriptor);
    assert.ok([...h.timers.values()].some(t=>t.delay===50));
});
test('reentrant timer cancellation during a tick leaves no stale runner', () => {
    const h = harness(), handle=h.register(); let ticks=0;
    h.context.globalScope.clockTick=function(){ticks++;h.context.clearTimeout(handle);};
    h.api.setEnabled(true);h.task();
    assert.equal(ticks,1); assert.equal(h.api.snapshot().registrations,0);
    assert.equal(h.tasks.length,0);
});
