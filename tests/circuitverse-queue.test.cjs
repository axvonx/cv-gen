const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const Queue = require('./fixtures/circuitverse-event-queue.cjs');
const {install} = require('../tools/circuitverse-queue-experiment.js');

function replay(operations, definitions, capacity = 64) {
    const queues = [new Queue(capacity), new Queue(capacity)];
    const objects = queues.map(() => definitions.map((definition, id) => ({
        id, propagationDelay: definition.delay, queueProperties: {...definition.properties},
    })));
    const restore = install(queues[1]);
    for (const [step, operation] of operations.entries()) {
        const results = queues.map((queue, side) => {
            try {
                const [method, id, delay] = operation;
                const result = method === 'add' ? queue.add(objects[side][id], delay)
                    : method === 'addImmediate' ? queue.addImmediate(objects[side][id])
                    : queue[method]();
                return {result: result?.id};
            } catch (error) { return {error: String(error)}; }
        });
        assert.deepEqual(results[1], results[0], `result at operation ${step}`);
        if (operation[0] === 'pop' && operation.length > 1)
            assert.equal(results[0].result, operation[1], `captured native pop at operation ${step}`);
        const compared = definitions.length <= 100 ? definitions.map((_, id) => id)
            : [...new Set([...queues[0].queue.slice(0, queues[0].frontIndex).map(obj => obj.id),
                ...queues[1].queue.slice(0, queues[1].frontIndex).map(obj => obj.id),
                ...(operation.length > 1 ? [operation[1]] : [])])];
        const state = (queue, side) => ({
            time: queue.time, frontIndex: queue.frontIndex,
            active: queue.queue.slice(0, queue.frontIndex).map(obj => obj.id),
            properties: compared.map(id => ({id, ...objects[side][id].queueProperties})),
        });
        assert.deepEqual(state(queues[1], 1), state(queues[0], 0), `state at operation ${step}`);
    }
    assert.deepEqual(objects[1].map(obj => obj.queueProperties),
        objects[0].map(obj => obj.queueProperties), 'final state of all objects');
    restore();
    assert.equal(Object.hasOwn(queues[1], 'add'), false);
    assert.equal(queues[1].add, Queue.prototype.add);
}

test('ties, priority updates in both directions, zero/default delays and capacity errors', () => {
    replay([
        ['add',0], ['add',1], ['add',2], ['add',0,1], ['add',2,9], ['add',3],
        ['add',1,0], ['pop'], ['pop'], ['add',0,-1], ['pop'], ['pop'], ['pop'],
        ['reset'], ['addImmediate',0], ['addImmediate',0], ['add',1],
        ['add',0,10], ['pop'], ['reset'], ['add',2], ['pop'],
    ], [{delay:5},{delay:5},{delay:2},{delay:1}], 3);
});

test('seeded differential operations preserve every pop and object property', () => {
    for (let seed = 1; seed <= 20; seed++) {
        let randomState = seed;
        const random = () => {
            randomState = (Math.imul(randomState, 1664525) + 1013904223) >>> 0;
            return randomState;
        };
        const definitions = Array.from({length:24}, () => ({delay: random()%8}));
        const operations = Array.from({length:4000}, () => {
            const kind = random()%100, id = random()%24;
            if (kind < 65) return ['add', id, [undefined,0,1,2,5,-1][random()%6]];
            if (kind < 88) return ['pop'];
            if (kind < 92) return ['addImmediate',id];
            return ['reset'];
        });
        replay(operations, definitions, 32);
    }
});

test('restore preserves exact own method descriptors', () => {
    const queue = new Queue(4);
    Object.defineProperty(queue, 'add', {value: queue.add, writable:true, configurable:true});
    const before = Object.getOwnPropertyDescriptors(queue);
    install(queue)();
    assert.deepEqual(Object.getOwnPropertyDescriptors(queue), before);
});

if (process.env.CV_QUEUE_TRACE) {
    test('captured native engine operations match the original queue', () => {
        const trace = JSON.parse(fs.readFileSync(process.env.CV_QUEUE_TRACE, 'utf8'));
        replay(trace.operations, trace.objects, trace.capacity);
    });
}
