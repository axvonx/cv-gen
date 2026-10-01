// ==UserScript==
// @name         CircuitVerse Turbo
// @namespace    https://github.com/axvonx/cv-gen
// @version      0.1.0
// @description  Adaptive runtime clock acceleration for CircuitVerse's default simulator in Firefox.
// @match        https://circuitverse.org/simulator*
// @run-at       document-start
// @sandbox      raw
// @grant        GM_registerMenuCommand
// @grant        unsafeWindow
// @noframes
// @license      MIT
// ==/UserScript==

(function circuitVerseTurbo() {
    'use strict';
    // Tampermonkey exposes a window proxy when GM grants are enabled.
    // Bind explicitly to the page window so hooks and the sentinel live there.
    const window = typeof unsafeWindow === 'undefined' ? globalThis.window : unsafeWindow;
    const key = '__circuitVerseTurbo';
    if (window[key]) return;
    const native = {
        interval: window.setInterval.bind(window),
        timeout: window.setTimeout.bind(window),
        clearInterval: window.clearInterval.bind(window),
        clearTimeout: window.clearTimeout.bind(window),
    };
    const supported = /^\/simulator\/?$/.test(location.pathname)
        && !location.search.includes('simver=')
        && /Firefox\//.test(navigator.userAgent) && window === window.top;
    // We cannot recover a timer registered before this script. Never guess IDs.
    const late = document.readyState !== 'loading' || !!window.globalScope;
    const timers = new Map();
    let nextHandle = -1, enabled = false, epoch = 0, pending = null, poll = null;
    let budget = 8, fault = '', status = 'Waiting for clock hook', slowUntil = 0;
    let edges = 0, tickMs = 0, measuredTicks = 0, sampleAt = performance.now();
    let rate = 0, average = 0, lastFrame = null, badFrames = 0, goodFrames = 0;
    let maxFrameGap = 0, frameGaps = 0, totalEdges = 0, lastTickMs = 0;
    let host, root, toggleButton, statusLabel, metrics, body, collapseButton;
    const channel = new MessageChannel();

    function recognizes(callback) {
        if (typeof callback !== 'function' || callback.name !== 'clockTick') return false;
        const source = Function.prototype.toString.call(callback);
        // Inspected legacy and current production callback. Names are intentionally
        // strict: new/minified implementations fail closed until inspected.
        return /\bglobalScope\s*\.\s*clockTick\s*\(/.test(source)
            && /\bclockEnabled\b/.test(source)
            && /\berrorDetectedGet\s*\(/.test(source)
            && /\blayoutModeGet\s*\(/.test(source)
            && /\bnextCycle\s*\(/.test(source)
            && /\bplay\s*\(/.test(source)
            && /\bscheduleUpdate\s*\(/.test(source);
    }
    function active() { return timers.size === 1 ? timers.values().next().value : null; }
    function runnable() { return enabled && !fault && supported && !late && !!active() && !document.hidden; }
    function resetMeasurements() {
        edges = tickMs = measuredTicks = rate = average = 0;
        sampleAt = performance.now();
        lastFrame = null;
        badFrames = goodFrames = 0;
        maxFrameGap = frameGaps = 0;
    }
    function stop() {
        epoch++;
        if (poll !== null) native.clearTimeout(poll);
        poll = null;
        // A posted message cannot be unposted. Its epoch prevents any clock work.
        // Keep pending until delivery so there is never more than one posted task.
    }
    function post() {
        if (!runnable() || pending !== null || poll !== null) return;
        pending = epoch;
        channel.port2.postMessage(epoch);
    }
    function wait() {
        if (!runnable() || poll !== null) return;
        poll = native.timeout(() => { poll = null; post(); }, 250);
    }
    function hasClocks(scope, seen = new Set()) {
        if (!scope || seen.has(scope)) return false;
        seen.add(scope);
        if (scope.Clock?.length) return true;
        return (scope.SubCircuit || []).some(part => hasClocks(part.localScope, seen));
    }
    function preflight() {
        if (window.loading || !window.globalScope) return 'Loading';
        if (!hasClocks(window.globalScope)) return 'No clock in selected circuit';
        return '';
    }
    function observedTick(timer) {
        const scope = window.globalScope;
        if (!scope) { timer.callback.apply(window, timer.args); return false; }
        const descriptor = Object.getOwnPropertyDescriptor(scope, 'clockTick');
        const original = scope.clockTick;
        if (typeof original !== 'function' || (descriptor && !('value' in descriptor))) {
            throw new Error('Cannot observe scope clockTick');
        }
        let accepted = false;
        const wrapped = function (...args) {
            const result = original.apply(this, args);
            accepted = true;
            return result;
        };
        Object.defineProperty(scope, 'clockTick', descriptor
            ? { ...descriptor, value: wrapped }
            : { value: wrapped, writable: true, configurable: true, enumerable: false });
        const started = performance.now();
        try { timer.callback.apply(window, timer.args); }
        finally {
            if (descriptor) Object.defineProperty(scope, 'clockTick', descriptor);
            else if (!Reflect.deleteProperty(scope, 'clockTick')) throw new Error('Cannot restore clockTick');
        }
        lastTickMs = performance.now() - started;
        if (accepted) {
            edges++; totalEdges++; measuredTicks++; tickMs += lastTickMs;
        }
        return accepted;
    }
    function fail(error) {
        fault = `Turbo stopped: ${error?.message || error}`;
        enabled = false;
        reconcile();
        console.error('[CircuitVerse Turbo]', error);
    }
    function startNative(timer) {
        if (timer.nativeId !== null) return;
        timer.nativeId = native.interval(function () {
            if (fault || timers.size !== 1) return timer.callback.apply(window, timer.args);
            try { observedTick(timer); }
            catch (error) { fail(error); }
        }, timer.delay);
    }
    function reconcile() {
        stop();
        for (const timer of timers.values()) {
            if (runnable()) {
                if (timer.nativeId !== null) native.clearInterval(timer.nativeId);
                timer.nativeId = null;
            } else if (enabled && !fault && timers.size === 1 && document.hidden) {
                // Turbo owns the clock while hidden; native scheduling is also stopped.
                if (timer.nativeId !== null) native.clearInterval(timer.nativeId);
                timer.nativeId = null;
            } else startNative(timer);
        }
        post();
        updatePanel();
    }
    channel.port1.onmessage = event => {
        pending = null;
        if (event.data !== epoch) { post(); return; }
        if (!runnable()) return;
        try {
            const reason = preflight();
            if (reason) { status = reason; wait(); return; }
            const timer = active(), token = epoch, started = performance.now();
            for (let count = 0; count < 256 && runnable() && epoch === token; count++) {
                const reason = preflight();
                if (reason) { status = reason; wait(); return; }
                if (!observedTick(timer)) {
                    status = 'Native pause / layout mode / simulator error';
                    wait(); return;
                }
                status = 'Turbo running';
                if (lastTickMs > 100) {
                    slowUntil = performance.now() + 2000;
                    budget = Math.max(2, budget / 2);
                    break;
                }
                if (performance.now() - started >= budget) break;
            }
            post();
        } catch (error) { fail(error); }
    };
    if (supported && !late) {
        window.setInterval = function (callback, delay, ...args) {
            if (!recognizes(callback)) return native.interval(callback, delay, ...args);
            const handle = nextHandle--;
            timers.set(handle, { callback, delay, args, nativeId: null });
            if (timers.size > 1) enabled = false;
            reconcile();
            return handle;
        };
        const cancel = (handle, clear) => {
            const timer = timers.get(handle);
            if (!timer) return clear(handle);
            if (timer.nativeId !== null) native.clearInterval(timer.nativeId);
            timers.delete(handle);
            reconcile();
        };
        window.clearInterval = handle => cancel(handle, native.clearInterval);
        window.clearTimeout = handle => cancel(handle, native.clearTimeout);
    }
    function setEnabled(value) {
        enabled = !!value && supported && !late && !fault && timers.size === 1;
        budget = 8;
        resetMeasurements();
        reconcile();
    }
    function currentStatus() {
        if (!supported) return 'Unsupported: Firefox default /simulator only';
        if (late) return 'Reload required: clock may predate interception';
        if (fault) return fault;
        if (timers.size > 1) return 'Unsupported: ambiguous clock registrations';
        if (!timers.size) return document.readyState === 'loading'
            ? 'Waiting for clock hook' : 'Unsupported: clock hook not found';
        if (!enabled) return 'Normal speed';
        if (document.hidden) return 'Suspended: hidden tab';
        if (performance.now() < slowUntil) return 'Slow simulation tick; yielding';
        return status;
    }
    function snapshot() {
        return { enabled, status: currentStatus(), edgesPerSecond: rate,
            averageTickMs: average, budgetMs: budget, totalEdges, lastTickMs,
            maxFrameGapMs: maxFrameGap, frameGapsOver100Ms: frameGaps,
            registrations: timers.size, pending: pending !== null, polling: poll !== null };
    }
    function updatePanel() {
        const elapsed = performance.now() - sampleAt;
        if (elapsed >= 500) {
            rate = edges * 1000 / elapsed;
            average = measuredTicks ? tickMs / measuredTicks : 0;
            edges = tickMs = measuredTicks = 0;
            sampleAt = performance.now();
        }
        if (!root) return;
        toggleButton.textContent = enabled ? 'Turbo on' : 'Turbo off';
        toggleButton.setAttribute('aria-pressed', String(enabled));
        toggleButton.disabled = !supported || late || !!fault || timers.size !== 1;
        statusLabel.textContent = currentStatus();
        metrics.textContent = `${rate.toFixed(0)} edges/s · ${average.toFixed(2)} ms/tick · ${budget} ms batch`;
    }
    function showPanel() {
        if (body) {
            body.hidden = false;
            collapseButton.textContent = '−';
            collapseButton.setAttribute('aria-label', 'Collapse panel');
        }
    }
    function mountPanel() {
        if (host || !document.body) return;
        host = document.createElement('div');
        host.id = 'circuitverse-turbo-panel';
        host.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:2147483647;max-width:calc(100vw - 24px)';
        root = host.attachShadow({ mode: 'open' });
        root.innerHTML = `<style>
            :host{font:12px/1.45 system-ui,sans-serif;color:#172b24}
            section{width:260px;max-width:calc(100vw - 24px);box-sizing:border-box;background:#fff;border:1px solid #b7c9c0;border-radius:8px;box-shadow:0 3px 16px #0002;padding:10px}
            header{display:flex;align-items:center;justify-content:space-between;gap:8px}
            button{font:inherit;cursor:pointer;border:1px solid #afc3b9;border-radius:5px;background:#f4f8f6;color:#172b24;padding:4px 8px}
            button[aria-pressed=true]{background:#176f4c;color:#fff}button:disabled{opacity:.6;cursor:default}
            p{margin:8px 0 0;overflow-wrap:anywhere}.note{color:#576b60;font-size:11px}
            [hidden]{display:none}
            </style><section aria-label="CircuitVerse Turbo"><header><strong>CircuitVerse Turbo</strong><button id="collapse" aria-label="Collapse panel">−</button></header>
            <div id="body"><p><button id="toggle" aria-pressed="false">Turbo off</button></p><p id="status" role="status"></p><p id="metrics"></p>
            <p class="note">Native period stays unchanged. Use ordinary clock pause. Turbo may increase CPU use.</p></div></section>`;
        toggleButton = root.getElementById('toggle');
        statusLabel = root.getElementById('status');
        metrics = root.getElementById('metrics');
        body = root.getElementById('body');
        collapseButton = root.getElementById('collapse');
        toggleButton.onclick = () => setEnabled(!enabled);
        collapseButton.onclick = () => {
            body.hidden = !body.hidden;
            collapseButton.textContent = body.hidden ? '+' : '−';
            collapseButton.setAttribute('aria-label', body.hidden ? 'Restore panel' : 'Collapse panel');
        };
        document.body.appendChild(host);
        updatePanel();
    }
    function animationFrame(now) {
        if (!document.hidden) {
            if (lastFrame !== null) {
                const gap = now - lastFrame;
                maxFrameGap = Math.max(maxFrameGap, gap);
                if (gap > 100) {
                    frameGaps++;
                    goodFrames = 0;
                    if (++badFrames >= 2) { budget = Math.max(2, budget / 2); badFrames = 0; }
                } else if (gap < 40) {
                    if (++goodFrames >= 120) { budget = Math.min(8, budget + 1); goodFrames = badFrames = 0; }
                } else goodFrames = 0;
            }
            lastFrame = now;
        }
        window.requestAnimationFrame(animationFrame);
    }
    document.addEventListener('visibilitychange', () => {
        resetMeasurements();
        reconcile();
    });
    if (document.body) mountPanel();
    else document.addEventListener('DOMContentLoaded', mountPanel, { once: true });
    native.interval(updatePanel, 500);
    window.requestAnimationFrame(animationFrame);
    Object.defineProperty(window, key, {
        value: Object.freeze({ setEnabled, snapshot, showPanel }), configurable: false,
    });
    if (typeof GM_registerMenuCommand === 'function') {
        GM_registerMenuCommand('Toggle CircuitVerse Turbo', () => setEnabled(!enabled));
        GM_registerMenuCommand('Restore Turbo panel', showPanel);
    }
})();
