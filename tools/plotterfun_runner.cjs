/* Local adapter for the pinned MIT-licensed Plotterfun workers. No network. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { Worker, isMainThread, parentPort, workerData } = require('node:worker_threads');

if (isMainThread) {
  let input = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', part => { input += part; });
  process.stdin.on('end', () => {
    try {
      const request = JSON.parse(input);
      const worker = new Worker(__filename, { workerData: request });
      let result;
      const timer = setTimeout(() => {
        process.stderr.write('Plotterfun execution limit exceeded; no partial result exported.\n');
        process.exitCode = 1;
        worker.terminate();
      }, request.timeoutSeconds * 1000);
      worker.on('message', message => { result = message; });
      worker.on('error', error => {
        process.stderr.write(String(error.stack || error) + '\n');
        process.exitCode = 1;
      });
      worker.on('exit', code => {
        clearTimeout(timer);
        if (code || !result || process.exitCode) {
          process.exitCode = 1;
          if (!result) process.stderr.write('Plotterfun did not finish successfully.\n');
        } else {
          process.stdout.write(JSON.stringify(result));
        }
      });
    } catch (error) {
      process.stderr.write(String(error.stack || error) + '\n');
      process.exitCode = 1;
    }
  });
} else {
  const root = path.resolve(__dirname, '../third_party/plotterfun');
  const allowed = new Set([
    'squiggle', 'squiggleLeftRight', 'spiral', 'polyspiral', 'sawtooth',
    'stipple', 'delaunay', 'linedraw', 'mosaic', 'subline', 'springs',
    'waves', 'needles', 'implode', 'halftone', 'boxes', 'dots', 'jaggy',
    'longwave', 'linescan', 'woven', 'peano', 'margins',
  ]);
  if (!allowed.has(workerData.algorithm)) throw new Error('Unknown Plotterfun algorithm');
  let controls = [], latest = null, latestMessage = '', sent = false;
  let seed = workerData.seed >>> 0;
  const seededMath = Object.create(Math);
  seededMath.random = () => {
    seed += 0x6D2B79F5;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t ^= t + Math.imul(t ^ t >>> 7, 61 | t);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
  const sandbox = {
    Math: seededMath, setTimeout, clearTimeout, setImmediate, clearImmediate,
    console: { log() {}, warn() {}, error() {} },
    postMessage(message) {
      if (message[0] === 'sliders') controls = message[1];
      else if (message[0] === 'msg') latestMessage = String(message[1]);
      else if (message[0] === 'svg-path') throw new Error('Unadapted SVG output');
    },
  };
  const context = vm.createContext(sandbox);
  sandbox.importScripts = (...names) => {
    for (const name of names) {
      const resolved = path.resolve(root, name);
      if (!resolved.startsWith(root + path.sep) || !resolved.endsWith('.js')) {
        throw new Error('Invalid local worker dependency');
      }
      vm.runInContext(fs.readFileSync(resolved, 'utf8'), context, { filename: resolved });
    }
  };
  vm.runInContext('self = globalThis;', context);
  sandbox.importScripts(workerData.algorithm + '.js');
  const config = { width: workerData.width, height: workerData.height };
  // The website retains common controls when switching algorithms. Isolated
  // workers need those defaults too (Linescan declares only its own controls).
  const allControls = [...(sandbox.defaultControls || []), ...controls];
  for (const control of allControls) {
    config[control.label] = control.type === 'checkbox' ? Boolean(control.checked)
      : control.value !== undefined ? control.value
      : control.type === 'select' ? control.options[0] : 0;
  }
  for (const [key, value] of Object.entries(workerData.profileControls || {})) {
    if (Object.prototype.hasOwnProperty.call(config, key)) config[key] = value;
  }
  for (const [key, value] of Object.entries(workerData.controls || {})) {
    const control = allControls.find(item => item.label === key);
    if (!control) throw new Error('Unknown control: ' + key);
    if (control.type === 'checkbox') {
      if (typeof value !== 'boolean') throw new Error(key + ' must be boolean');
    } else if (control.type === 'select') {
      if (!control.options.includes(value)) throw new Error('Invalid option: ' + key);
    } else if (!Number.isFinite(value) || value < control.min || value > control.max) {
      throw new Error('Control out of range: ' + key);
    }
    config[key] = value;
  }
  // Capture geometry before SVG rounding and preserve point coordinates at zero.
  sandbox.postLines = data => {
    if (!data || !data.length) { latest = []; return; }
    const first = data[0];
    const single = (!Array.isArray(first) && typeof first === 'object' && 'x' in first)
      || (Array.isArray(first) && typeof first[0] === 'number');
    const paths = single ? [data] : data;
    latest = paths.map(poly => poly.map(point => Array.isArray(point)
      ? [point[0], point[1]] : [point.x, point.y]));
  };
  sandbox.postCircles = data => {
    latest = (data || []).map(circle => {
      const [x, y, radius] = Array.isArray(circle) ? circle : [circle.x, circle.y, circle.r];
      const r = Math.max(0.001, radius);
      const steps = Math.max(12, Math.min(2048, Math.ceil(2 * Math.PI * r / 1.25)));
      const points = [];
      for (let i = 0; i <= steps; i++) {
        const angle = i * 2 * Math.PI / steps;
        points.push([x + Math.cos(angle) * r, y + Math.sin(angle) * r]);
      }
      return points;
    });
  };
  const bytes = Buffer.from(workerData.rgba, 'base64');
  if (bytes.length !== config.width * config.height * 4) throw new Error('Invalid image dimensions');
  const image = { data: new Uint8ClampedArray(bytes), width: config.width, height: config.height };
  process.on('beforeExit', () => {
    if (sent) return;
    if (latest === null) throw new Error('Algorithm produced no vector result: ' + latestMessage);
    sent = true;
    const originalPaths = latest;
    const originalConfig = { ...config };
    let variants;
    if (workerData.batchStipples && workerData.algorithm === 'stipple') {
      // Reuse the original worker's optimized particles. Shape changes call
      // its own redraw function, not another costly Voronoi/TSP calculation.
      variants = {};
      for (const [key, shape] of Object.entries({
        stipple: 'Circles', 'stipple-spirals': 'Spirals',
        'stipple-hexagons': 'Hexagons', 'stipple-pentagrams': 'Pentagrams',
        'stipple-snowflakes': 'Snowflakes', tsp: 'Circles',
      })) {
        sandbox.onmessage({ data: [{ 'TSP Art': key === 'tsp', 'Stipple type': shape }] });
        variants[key] = latest;
      }
      Object.assign(config, originalConfig);
    }
    parentPort.postMessage({ paths: originalPaths, config: originalConfig, variants,
      message: latestMessage, complete: true });
  });
  const returned = sandbox.onmessage({ data: [config, image] });
  if (returned && typeof returned.then === 'function') {
    returned.catch(error => { throw error; });
  }
}
