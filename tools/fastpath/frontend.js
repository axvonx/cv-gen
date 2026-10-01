/** Source-level adapter for the pinned local CircuitVerse v0 frontend. */
import load from "./data/load";
import { scopeList, switchCircuit } from "./circuit";
import { simulationArea } from "./simulationArea";
import { clockTick } from "./utils";
import {
  play,
  renderCanvas,
  updateCanvasSet,
  errorDetectedGet,
  errorDetectedSet,
  forceResetNodesSet,
} from "./engine";
import { layoutModeGet, layoutModeSet } from "./layoutMode";
import modules from "./modules";
import Node from "./node";
import { EventQueue } from "./eventQueue";
import { SuperTurboController } from "./fastpath/controller.mjs";
import { fetchPackage } from "./fastpath/runtime.mjs";

export function initializeFastpath() {
  if (window.__cvFastpathHost) return;
  let packageInfo,
    internalLoad = false,
    scope,
    restorers = [],
    lastValues = {};
  const counters = { queue: 0, node: 0, component: 0, scopeClock: 0 };
  const host = {
    active: false,
    enter(info) {
      window.__circuitVerseTurbo?.setEnabled(false);
      clearInterval(simulationArea.ClockInterval);
      simulationArea.ClockInterval = null;
      const period = simulationArea.timePeriod;
      errorDetectedSet(false);
      internalLoad = true;
      try {
        load({ ...JSON.parse(info.projectText), clockEnabled: false, timePeriod: period });
      } finally {
        internalLoad = false;
      }
      errorDetectedSet(false);
      play();
      scope = scopeList[info.manifest.display.scopeId];
      if (!scope || scope.name !== "Demo") throw new Error("bound Demo scope missing");
      for (const port of info.manifest.ports) {
        const b = port.binding,
          component = scope[b.kind]?.[b.index];
        const node = b.kind === "Output" ? component?.inp1 : component?.output1;
        if (
          !component ||
          component.label !== b.label ||
          node?.bitWidth !== port.width ||
          scope.allNodes.indexOf(node) !== b.node
        )
          throw new Error(`incompatible live binding: ${port.name}`);
      }
      const matrix = scope.RGBLedMatrix[info.manifest.display.matrixIndex];
      if (
        matrix?.label !== info.manifest.display.matrixLabel ||
        matrix.rows !== info.manifest.display.size ||
        matrix.columns !== info.manifest.display.size
      )
        throw new Error("incompatible display binding");
      this.active = true;
      packageInfo = info;
      simulationArea.hover = undefined;
      // Neutralize stale internals; native values are restored by reloading on exit.
      for (const node of scope.allNodes) node.value = undefined;
      lastValues = Object.fromEntries(
        info.manifest.ports
          .filter((p) => p.direction === "input" && p.name !== "clk")
          .map((p) => [p.name, p.initial]),
      );
      for (const key of Object.keys(counters)) counters[key] = 0;
      const protect = (prototype, method, counter) => {
        const descriptor = Object.getOwnPropertyDescriptor(prototype, method);
        if (!descriptor || typeof descriptor.value !== "function") return;
        const original = descriptor.value;
        Object.defineProperty(prototype, method, {
          ...descriptor,
          value: function (...args) {
            if (host.active) {
              ++counters[counter];
              throw new Error(`native ${method} in Super Turbo`);
            }
            return original.apply(this, args);
          },
        });
        restorers.push(() => Object.defineProperty(prototype, method, descriptor));
      };
      for (const method of ["add", "addImmediate", "pop"])
        protect(EventQueue.prototype, method, "queue");
      protect(Node.prototype, "resolve", "node");
      for (const module of Object.values(modules))
        protect(module.prototype, "resolve", "component");
      protect(Object.getPrototypeOf(scope), "clockTick", "scopeClock");
      document.body.classList.add("cv-super-active");
      forceResetNodesSet(false);
    },
    leave() {
      this.active = false;
      for (const restore of restorers.splice(0).reverse()) restore();
      document.body.classList.remove("cv-super-active");
      if (packageInfo) {
        const period = simulationArea.timePeriod;
        errorDetectedSet(false);
        internalLoad = true;
        try {
          load({ ...JSON.parse(packageInfo.projectText), clockEnabled: false, timePeriod: period });
        } finally {
          internalLoad = false;
        }
        errorDetectedSet(false);
        play();
      }
      simulationArea.clockEnabled = false;
      simulationArea.changeClockTime(simulationArea.timePeriod);
    },
    beforeImport(data) {
      if (internalLoad) return;
      if (this.active) {
        controller.dispose();
        this.active = false;
        for (const restore of restorers.splice(0).reverse()) restore();
        document.body.classList.remove("cv-super-active");
        packageInfo = undefined;
        controller.status = "Project changed — rebuild/reload package";
      }
      if (data) data.clockEnabled = false;
    },
    blocked() {
      if (document.hidden) return "Hidden tab — suspended";
      if (window.loading) return "Loading";
      if (String(globalScope?.id) !== String(scope?.id)) return "Selected circuit unavailable";
      if (layoutModeGet()) return "Layout mode — paused";
      if (errorDetectedGet()) {
        controller.fail("simulator error");
        return "Simulator error";
      }
      return null;
    },
    present(snapshot) {
      if (!this.active || !scope) return;
      Object.assign(lastValues, snapshot.inputs);
      for (const port of packageInfo.manifest.ports) {
        const component = scope[port.binding.kind][port.binding.index];
        if (port.direction === "output") component.inp1.value = snapshot.outputs[port.name];
        else if (port.name === "clk") {
          component.state = snapshot.clock;
          component.output1.value = snapshot.clock;
        } else {
          component.state = lastValues[port.name];
          component.output1.value = lastValues[port.name];
        }
      }
      const size = packageInfo.manifest.display.size;
      const matrix = scope.RGBLedMatrix[packageInfo.manifest.display.matrixIndex];
      matrix.colors = Array.from({ length: size }, (_, r) =>
        Array.from(snapshot.pixels.slice(r * size, (r + 1) * size)),
      );
      if (globalScope === scope && !layoutModeGet()) renderCanvas(scope);
    },
    syncInputs() {
      if (!this.active || !packageInfo) return;
      const changes = {};
      for (const port of packageInfo.manifest.ports.filter(
        (p) => p.direction === "input" && p.name !== "clk",
      )) {
        const value = scope[port.binding.kind][port.binding.index].state;
        if (value !== lastValues[port.name]) changes[port.name] = value;
      }
      if (Object.keys(changes).length)
        this.setInputs(changes).catch((e) => controller.fail(e.message));
    },
    async setInputs(changes) {
      const result = await controller.applyInputs(changes);
      Object.assign(lastValues, changes);
      this.present(result);
      return result;
    },
    circuitChanging(id) {
      if (this.active && String(id) !== String(scope?.id)) controller.pause();
    },
  };
  const controller = new SuperTurboController(host);
  window.__cvFastpathHost = host;
  window.__cvSuperTurbo = controller;
  window.__cvTest = {
    loadJSON: (text) => load(JSON.parse(text)),
    load,
    simulationArea,
    switchCircuit,
    scopes: () => scopeList,
    play,
    clockTick,
    errorDetectedGet,
    errorDetectedSet,
    layoutModeSet,
    nativeCounters: () => ({ ...counters }),
    setInputs: (changes) => host.setInputs(changes),
  };

  const style = document.createElement("style");
  style.textContent = `#cv-super-panel{position:fixed;right:14px;bottom:14px;z-index:10000;
    background:#20242b;color:#fff;padding:12px;border-radius:8px;width:290px;font:13px sans-serif;
    box-shadow:0 3px 14px #0006}#cv-super-panel button{margin:3px;padding:4px 8px}
    #cv-super-panel small{display:block;margin:6px 0;color:#ccd2dc}
    #cv-super-panel input{width:95px;margin:3px}#cv-super-panel label{display:block}
    .cv-super-active #Properties,.cv-super-active #plotArea{pointer-events:none;opacity:.4}`;
  document.head.append(style);
  const panel = document.createElement("section");
  panel.id = "cv-super-panel";
  panel.innerHTML = `<strong>Super Turbo</strong> <button data-action="collapse">−</button>
    <div data-content><div><button data-action="toggle">Enable</button>
    <button data-action="pause">Run / Pause</button><button data-action="reset">Reset</button>
    <button data-action="step">Step</button></div><p data-status>Native</p><small data-metrics></small>
    <small>Native period unchanged. Internal signals and timing unavailable while active.</small>
    <details><summary>Hardware inputs</summary><div data-inputs></div></details></div>`;
  document.body.append(panel);
  let lastStats = 0,
    lastEdges = 0;
  controller.subscribe((state) => {
    if (host.active) {
      simulationArea.clockEnabled = state.running;
      const nativePause = document.querySelector('[name="changeClockEnable"]');
      if (nativePause) nativePause.checked = state.running;
    }
    panel.querySelector("[data-status]").textContent = state.status;
    panel.querySelector('[data-action="toggle"]').textContent =
      state.mode === "super" ? "Disable" : "Enable";
    const now = performance.now();
    if (now - lastStats >= 250 || !state.running) {
      const throughput =
        now > lastStats ? ((state.edges - lastEdges) * 1000) / (now - lastStats) : 0;
      const times = state.frameTimes;
      const latency = times.length > 1 ? times.at(-1).time - times.at(-2).time : 0;
      panel.querySelector("[data-metrics]").textContent =
        `${Math.max(0, throughput).toFixed(0)} half-edges/s · ` +
        `${latency.toFixed(1)} ms/frame · ${state.durationMs.toFixed(1)} ms batch`;
      lastStats = now;
      lastEdges = state.edges;
    }
  });
  const safely = (action) =>
    Promise.resolve()
      .then(action)
      .catch((e) => controller.fail(e.message));
  panel.addEventListener("click", (event) => {
    const action = event.target.dataset.action;
    if (action === "collapse") {
      const content = panel.querySelector("[data-content]");
      content.hidden = !content.hidden;
    } else if (action === "toggle")
      safely(async () => {
        if (controller.mode === "super") await controller.setMode("native");
        else {
          if (!packageInfo)
            throw new Error("No compatible package; load the packaged simulator URL");
          await controller.setMode("super", packageInfo);
          controller.resume();
        }
      });
    else if (action === "pause") {
      if (controller.mode === "super")
        safely(() => (controller.running ? controller.pause() : controller.resume()));
      else simulationArea.clockEnabled = !simulationArea.clockEnabled;
    } else if (action === "reset") safely(() => controller.reset());
    else if (action === "step") safely(() => controller.stepHalfEdge());
  });
  document.addEventListener("visibilitychange", () => {
    if (host.active) {
      controller.pump();
      controller.notify();
    }
  });
  // Watch native controls and layout/visibility without creating an execution backlog.
  setInterval(() => {
    if (host.active) {
      host.syncInputs();
      controller.pump();
    }
  }, 250);

  // Block mutation handlers while active. Inputs use the explicit panel API; canvas
  // drag pans directly, wheel zoom remains native. Tabs and Fit to Screen are safe.
  let drag;
  const nativeClockControl = (target) =>
    target.closest(".input-group")?.querySelector("#clockTime") ||
    target.closest("label.switch")?.querySelector('[name="changeClockEnable"]');
  document.addEventListener(
    "mousedown",
    (event) => {
      if (!host.active || event.target.closest("#cv-super-panel")) return;
      if (nativeClockControl(event.target)) return;
      if (event.target.id === "simulationArea") drag = { x: event.clientX, y: event.clientY };
      event.stopImmediatePropagation();
      event.preventDefault();
    },
    true,
  );
  document.addEventListener(
    "mousemove",
    (event) => {
      if (!host.active || !drag) return;
      globalScope.ox += event.clientX - drag.x;
      globalScope.oy += event.clientY - drag.y;
      drag = { x: event.clientX, y: event.clientY };
      renderCanvas(globalScope);
      event.stopImmediatePropagation();
    },
    true,
  );
  document.addEventListener(
    "mouseup",
    () => {
      drag = undefined;
    },
    true,
  );
  for (const name of [
    "click",
    "dblclick",
    "keydown",
    "dragstart",
    "drop",
    "cut",
    "paste",
    "touchstart",
  ])
    document.addEventListener(
      name,
      (event) => {
        if (!host.active || event.target.closest("#cv-super-panel")) return;
        if (nativeClockControl(event.target)) return;
        if (event.target.closest("#driver-popover-item")) return;
        if (
          name === "click" &&
          (event.target.closest(".tabsbar") ||
            event.target.closest('button[title="Fit to Screen"]'))
        )
          return;
        event.preventDefault();
        event.stopImmediatePropagation();
      },
      true,
    );

  const ready = setInterval(async () => {
    if (!globalScope || !simulationArea.context) return;
    clearInterval(ready);
    const requested = new URL(location.href).searchParams.get("fastpath");
    if (!requested) return;
    try {
      const base = new URL(requested.endsWith("/") ? requested : requested + "/", location.href);
      if (base.origin !== location.origin)
        throw new Error("package must be served locally with simulator");
      packageInfo = { ...(await fetchPackage(base)), base };
      localStorage.setItem("tutorials_tour_done", "true");
      document.querySelector(".driver-close-btn")?.click();
      internalLoad = true;
      try {
        load({ ...JSON.parse(packageInfo.projectText), clockEnabled: false });
      } finally {
        internalLoad = false;
      }
      simulationArea.clockEnabled = false;
      const inputs = panel.querySelector("[data-inputs]");
      for (const port of packageInfo.manifest.ports.filter(
        (p) => p.direction === "input" && p.name !== "clk",
      )) {
        const label = document.createElement("label");
        label.textContent = port.name + " ";
        const field = document.createElement("input");
        field.type = "number";
        field.min = "0";
        field.max = String(2 ** port.width - 1);
        field.value = port.initial;
        field.addEventListener("change", () =>
          safely(() => host.setInputs({ [port.name]: Number(field.value) })),
        );
        label.append(field);
        inputs.append(label);
      }
      controller.status = "Compatible package — Super Turbo off";
      controller.notify();
      window.__cvFastpathPackage = packageInfo;
      document.querySelector(".tabsbar-toggle .fa-chevron-up")?.closest("button").click();
      document.querySelector('button[title="Fit to Screen"]')?.click();
    } catch (error) {
      controller.fail(error.message);
    }
  }, 50);
}
