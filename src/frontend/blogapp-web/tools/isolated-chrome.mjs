import { spawn } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { performance } from 'node:perf_hooks';

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const OUTPUT_LIMIT = 16384;

function debuggerOrigin(value, protocol) {
  try {
    const url = new URL(value);
    if (url.protocol !== protocol || !['127.0.0.1', '[::1]'].includes(url.hostname)
      || !url.port || url.username || url.password || url.search || url.hash
      || !url.pathname.startsWith('/devtools/browser/')) return null;
    return `http://${url.host}`;
  } catch { return null; }
}

function portOrigin(text) {
  const port = text.split(/\r?\n/, 1)[0];
  return /^\d+$/.test(port) && Number(port) > 0 && Number(port) <= 65535
    ? `http://127.0.0.1:${Number(port)}` : null;
}

// A CDP listener must answer before it counts as readiness. A partial/stale file
// and Chrome's "DevTools listening" log are discovery hints, not success.
async function versionAt(origin, remainingMs, request) {
  const controller = new AbortController();
  let timer;
  try {
    return await Promise.race([
      (async () => {
        const response = await request(`${origin}/json/version`, { signal: controller.signal, redirect: 'error' });
        if (!response.ok) throw new Error(`DevTools HTTP ${response.status}`);
        const version = await response.json();
        if (typeof version.Browser !== 'string' || !version.Browser.trim()
          || debuggerOrigin(version.webSocketDebuggerUrl, 'ws:') !== origin) {
          throw new Error('Invalid local DevTools version response');
        }
        return version;
      })(),
      new Promise((_, reject) => { timer = setTimeout(() => {
        controller.abort(); reject(new Error('DevTools readiness request timed out'));
      }, Math.min(500, Math.max(1, remainingMs))); }),
    ]);
  } finally { clearTimeout(timer); }
}

/** One owned process, one private profile, one fixed startup budget. */
export async function startChromeAttempt({ executablePath, profilePath, timeoutMs = 15000, cleanupTimeoutMs = 1000,
  spawnProcess = spawn, readPortFile = readFile, request = fetch, platform = process.platform,
  signalGroup = (pid, signal) => process.kill(-pid, signal) }) {
  const started = performance.now();
  const diagnostics = { executablePath, profilePath, timeoutMs, pid: null, state: 'starting',
    exitCode: null, signal: null, spawnError: null, stdout: '', stderr: '',
    portFile: 'not observed', lastReadinessError: null, discovery: null, cleanupState: 'not requested',
    processGroup: platform === 'win32' ? null : 'owned detached group' };
  let child;
  let exited = false;
  let closed = false;
  let stopped = false;
  let endpointFromLog = null;
  let closeResolve;
  const closePromise = new Promise(resolve => { closeResolve = resolve; });
  const args = ['--headless=new', '--no-first-run', '--no-default-browser-check',
    '--disable-background-networking', '--disable-default-apps', '--disable-extensions', '--disable-sync',
    `--user-data-dir=${profilePath}`, '--remote-debugging-port=0', 'about:blank'];
  const snapshot = () => ({ ...diagnostics, elapsedMs: Math.round(performance.now() - started) });
  const waitForClose = async () => {
    let timer;
    try { await Promise.race([closePromise, new Promise(resolve => { timer = setTimeout(resolve, cleanupTimeoutMs); })]); }
    finally { clearTimeout(timer); }
  };
  const groupExists = () => {
    try { signalGroup(child.pid, 0); return true; }
    catch (error) { if (error.code === 'ESRCH') return false; throw error; }
  };
  const stopGroup = async signal => {
    try { signalGroup(child.pid, signal); }
    catch (error) { if (error.code !== 'ESRCH') throw error; }
    const deadline = performance.now() + cleanupTimeoutMs;
    while (groupExists() && performance.now() < deadline) await pause(25);
    return !groupExists();
  };
  const stop = async () => {
    if (stopped) return snapshot();
    let reaped = closed || !child;
    if (child?.pid && platform !== 'win32') {
      // detached:true makes PID the process-group ID owned by this invocation.
      // Signal that group even if a launcher wrapper has already exited.
      reaped = await stopGroup('SIGTERM');
      if (!reaped) reaped = await stopGroup('SIGKILL');
      await waitForClose();
      reaped = reaped && closed;
    } else if (child && !closed) {
      child.kill(); await waitForClose();
      if (!closed) { child.kill('SIGKILL'); await waitForClose(); }
      reaped = closed;
    }
    diagnostics.cleanupState = reaped ? 'closed' : 'failed';
    if (diagnostics.cleanupState === 'failed') {
      const error = new Error(`Owned Chrome process did not close after termination; ${JSON.stringify(snapshot())}`);
      error.diagnostics = { ...snapshot(), state: 'cleanup-failed' };
      throw error;
    }
    stopped = true;
    return snapshot();
  };
  const fail = async (state, reason) => {
    diagnostics.state = state;
    // A launch that fails must be reaped before a fresh profile can be tried.
    await stop();
    const error = new Error(`Isolated Chrome ${reason}; ${JSON.stringify(snapshot())}`);
    error.diagnostics = snapshot();
    throw error;
  };
  try {
    child = spawnProcess(executablePath, args, { windowsHide: true, detached: platform !== 'win32',
      stdio: ['ignore', 'pipe', 'pipe'] });
    diagnostics.pid = child.pid ?? null;
    child.on('error', error => { diagnostics.spawnError = `${error.code ?? error.name}: ${error.message}`; });
    child.on('exit', (code, signal) => { exited = true; diagnostics.exitCode = code; diagnostics.signal = signal; });
    child.on('close', () => { closed = true; closeResolve(); });
    for (const stream of ['stdout', 'stderr']) child[stream]?.on('data', bytes => {
      diagnostics[stream] = (diagnostics[stream] + bytes.toString()).slice(-OUTPUT_LIMIT);
      const matches = [...diagnostics[stream].matchAll(/DevTools listening on (ws:\/\/[^\s]+)/g)];
      for (const match of matches) endpointFromLog = debuggerOrigin(match[1], 'ws:') ?? endpointFromLog;
    });
  } catch (error) {
    diagnostics.spawnError = `${error.code ?? error.name}: ${error.message}`;
  }
  while (performance.now() - started < timeoutMs) {
    if (diagnostics.spawnError) return fail('spawn-error', 'failed to spawn');
    if (exited) return fail('early-exit', 'exited before becoming ready');
    const endpoints = new Map();
    try {
      const contents = await readPortFile(path.join(profilePath, 'DevToolsActivePort'), 'utf8');
      const origin = portOrigin(contents);
      diagnostics.portFile = origin ? 'valid port' : 'incomplete or invalid';
      if (origin) endpoints.set(origin, 'DevToolsActivePort');
    } catch (error) { diagnostics.portFile = error.code ?? error.name; }
    if (endpointFromLog && !endpoints.has(endpointFromLog)) endpoints.set(endpointFromLog, 'DevTools listening log');
    for (const [origin, discovery] of endpoints) {
      const remaining = timeoutMs - (performance.now() - started);
      if (remaining <= 0) break;
      try {
        const version = await versionAt(origin, remaining, request);
        if (diagnostics.spawnError) return fail('spawn-error', 'failed to spawn');
        if (exited) return fail('early-exit', 'exited before becoming ready');
        diagnostics.state = 'ready'; diagnostics.discovery = discovery;
        return { process: child, origin, version, diagnostics: snapshot(), stop };
      } catch (error) { diagnostics.lastReadinessError = `${error.name}: ${error.message}`; }
    }
    await pause(Math.min(50, Math.max(0, timeoutMs - (performance.now() - started))));
  }
  if (diagnostics.spawnError) return fail('spawn-error', 'failed to spawn');
  if (exited) return fail('early-exit', 'exited before becoming ready');
  return fail('readiness-timeout', 'readiness timed out while the process was still running');
}

/** Retry startup only once, and only for a still-running readiness timeout. */
export async function launchIsolatedChrome({ executablePath, profilePath, onAttempt = async () => {}, ...options }) {
  const attempts = [];
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      const browser = await startChromeAttempt({ ...options, executablePath,
        profilePath: attempt === 1 ? profilePath : `${profilePath}-retry` });
      attempts.push({ attempt, ...browser.diagnostics });
      try { await onAttempt(attempts); }
      catch (error) { await browser.stop(); throw error; }
      return { ...browser, attempts };
    } catch (error) {
      if (!error.diagnostics) throw error;
      attempts.push({ attempt, ...error.diagnostics });
      await onAttempt(attempts);
      if (attempt === 2 || error.diagnostics.state !== 'readiness-timeout') throw error;
    }
  }
  throw new Error('Unreachable Chrome launch state');
}
