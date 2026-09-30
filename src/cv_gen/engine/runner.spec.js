/**
 * @jest-environment jsdom
 */
// cv-gen headless runner: runs every testbench embedded in a .cv project through
// CircuitVerse's legacy simulator engine and writes a JSON report.
// Env: CV_PROJECT (input .cv), CV_REPORT (output json), CV_ONLY (JSON list of scope
// names, optional), CV_MAXFAIL (failures kept per scope, default 5), CV_RESULTS (JSON
// list of scope names whose full per-output results are included, for calibration).
import fs from 'fs';

// Rendering is irrelevant to simulation: give every canvas a no-op 2D context.
const noop = () => {};
const ctx = new Proxy({}, {
    get: (_t, p) => (p === 'measureText' ? () => ({ width: 0 }) : p === 'canvas' ? {} : noop),
    set: () => true,
});
HTMLCanvasElement.prototype.getContext = () => ctx;

jest.mock('codemirror');

test('cv-gen runner', () => {
    const report = { version: 1, project: null, loadMs: null, loadError: null, scopes: [] };
    const write = () => fs.writeFileSync(process.env.CV_REPORT, JSON.stringify(report));
    try {
        run(report);
    } catch (e) {
        report.loadError = String(e && e.stack ? e.stack : e);
    }
    write();
});

function run(report) {
    const CodeMirror = require('codemirror');
    CodeMirror.fromTextArea.mockReturnValue({ setValue: noop });
    const { setup } = require('../src/setup');
    const load = require('../src/data/load').default;
    const { runAll } = require('../src/testbench');
    const { switchCircuit, scopeList } = require('../src/circuit');
    const { errorDetectedGet, errorDetectedSet } = require('../src/engine');

    setup();
    const project = JSON.parse(fs.readFileSync(process.env.CV_PROJECT, 'utf8'));
    report.project = project.name;
    const t0 = performance.now();
    load(project);
    report.loadMs = Math.round(performance.now() - t0);

    const only = process.env.CV_ONLY ? new Set(JSON.parse(process.env.CV_ONLY)) : null;
    const maxFail = Number(process.env.CV_MAXFAIL) || 5;
    const dump = process.env.CV_RESULTS ? new Set(JSON.parse(process.env.CV_RESULTS)) : new Set();
    for (const s of project.scopes) {
        if (only && !only.has(s.name)) continue;
        const base = { scope: s.name, id: String(s.id) };
        const tb = s.testbenchData && s.testbenchData.testData;
        if (!tb) { report.scopes.push({ ...base, status: 'no-tests' }); continue; }
        let r;
        const start = performance.now();
        try {
            switchCircuit(String(s.id));
            errorDetectedSet(false);
            r = runAll(JSON.parse(JSON.stringify(tb)), scopeList[s.id]);
        } catch (e) {
            report.scopes.push({ ...base, status: 'crash', error: String(e) });
            continue;
        }
        const ms = performance.now() - start;
        // play() silently stops simulating once an engine error is flagged, leaving
        // stale outputs; such a run proves nothing either way.
        const engineError = errorDetectedGet();
        const failures = [];
        for (const g of r.detailed.groups) {
            for (let i = 0; i < g.n && failures.length < maxFail; i++) {
                const bad = g.outputs.filter((o) => o.values[i] !== o.results[i]);
                if (bad.length) {
                    failures.push({
                        group: g.label,
                        case: i,
                        inputs: Object.fromEntries(g.inputs.map((x) => [x.label, x.values[i]])),
                        diffs: bad.map((o) => ({ output: o.label, expected: o.values[i], got: o.results[i] })),
                    });
                }
            }
        }
        const { passed, total } = r.summary;
        report.scopes.push({
            ...base,
            status: engineError ? 'engine-error' : passed === total ? 'pass' : 'fail',
            ...(engineError ? { error: $('.alert-danger').text() } : {}),
            passed,
            total,
            ms: Math.round(ms),
            failures,
            ...(dump.has(s.name) ? {
                results: r.detailed.groups.map((g) => Object.fromEntries(g.outputs.map((o) => [o.label, o.results]))),
            } : {}),
        });
    }
}
