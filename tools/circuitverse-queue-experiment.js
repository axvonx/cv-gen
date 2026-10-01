/* Local engine experiment only; deliberately not included in the userscript. */
const circuitVerseQueueExperiment = (() => {
    function install(queue) {
        const names = ['add', 'addImmediate', 'reset'];
        const descriptors = names.map(name => Object.getOwnPropertyDescriptor(queue, name));
        const original = Object.fromEntries(names.map(name => [name, queue[name]]));
        // Native addImmediate permits duplicate objects. Adjacent swaps then have
        // aliasing behavior that shifting does not reproduce; retain native add
        // until reset if this unusual interface behavior is used.
        let aliases = false;
        queue.addImmediate = function (obj) {
            if (obj.queueProperties.inQueue) aliases = true;
            return original.addImmediate.call(this, obj);
        };
        queue.reset = function () {
            const result = original.reset.call(this);
            aliases = false;
            return result;
        };
        queue.add = function (obj, delay) {
            if (aliases) return original.add.call(this, obj, delay);
            const properties = obj.queueProperties;
            const queued = properties.inQueue;
            if (!queued && this.frontIndex == this.size) throw 'EventQueue size exceeded';
            const time = this.time + (delay || obj.propagationDelay);
            properties.time = time;
            let i = queued ? properties.index : this.frontIndex++;
            const entries = this.queue;
            while (i > 0 && time > entries[i - 1].queueProperties.time) {
                const displaced = entries[i - 1];
                entries[i] = displaced;
                displaced.queueProperties.index = i;
                i--;
            }
            // Native new insertions only move left. Updates also move right.
            if (queued) {
                while (i < this.frontIndex - 1 && time < entries[i + 1].queueProperties.time) {
                    const displaced = entries[i + 1];
                    entries[i] = displaced;
                    displaced.queueProperties.index = i;
                    i++;
                }
            }
            entries[i] = obj;
            properties.index = i;
            properties.inQueue = true;
        };
        return function restore() {
            names.forEach((name, i) => {
                if (descriptors[i]) Object.defineProperty(queue, name, descriptors[i]);
                else delete queue[name];
            });
        };
    }
    return { install };
})();
if (typeof module !== 'undefined') module.exports = circuitVerseQueueExperiment;
