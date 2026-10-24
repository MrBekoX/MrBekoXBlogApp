import { EventEmitter } from 'node:events';
import { spawn } from 'node:child_process';
import { PassThrough } from 'node:stream';
import { describe, expect, it, vi } from 'vitest';
import { launchIsolatedChrome, startChromeAttempt } from '../../../tools/isolated-chrome.mjs';

const origin = 'http://127.0.0.1:43210';
const version = { Browser: 'Chrome/test', webSocketDebuggerUrl: 'ws://127.0.0.1:43210/devtools/browser/test' };
const missingFile = () => Promise.reject(Object.assign(new Error('Missing fixture file'), { code: 'ENOENT' }));
function processFixture(onStart = () => {}) {
  const child = Object.assign(new EventEmitter(), { pid: 1234, stdout: new PassThrough(), stderr: new PassThrough() });
  child.kill = vi.fn(signal => { queueMicrotask(() => {
    child.emit('exit', null, signal ?? 'SIGTERM'); child.emit('close', null, signal ?? 'SIGTERM');
  }); return true; });
  queueMicrotask(() => onStart(child));
  return child;
}
function fixture(options = {}) {
  const children = [];
  const spawnProcess = vi.fn(() => {
    const child = processFixture(options.onStart); children.push(child); return child;
  });
  const request = vi.fn(async () => ({ ok: true, json: async () => version }));
  return { children, spawnProcess, request, executablePath: 'fixture-chrome', profilePath: '/tmp/isolated-fixture',
    timeoutMs: 1000, platform: 'win32', readPortFile: missingFile, ...options };
}

describe('isolated Chrome startup', () => {
  it('validates the stderr DevTools endpoint even when the active-port file is absent', async () => {
    const options = fixture({ onStart: child => child.stderr.write(`DevTools listening on ${version.webSocketDebuggerUrl}\n`) });
    const browser = await startChromeAttempt(options);
    expect(browser.origin).toBe(origin);
    expect(browser.diagnostics.discovery).toBe('DevTools listening log');
    expect(browser.diagnostics.portFile).toBe('ENOENT');
    expect(options.request.mock.calls[0][0]).toBe(`${origin}/json/version`);
    expect(options.request.mock.calls[0][1].redirect).toBe('error');
    await browser.stop(); expect(options.children[0].kill).toHaveBeenCalledOnce();
  });

  it('waits for a complete port file and an answering HTTP endpoint', async () => {
    const readPortFile = vi.fn().mockResolvedValueOnce('').mockResolvedValue('43210\n/devtools/browser/test\n');
    const options = fixture({ readPortFile });
    options.request.mockRejectedValueOnce(new Error('ECONNREFUSED'));
    options.timeoutMs = 2000;
    const browser = await startChromeAttempt(options);
    expect(readPortFile.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(options.request).toHaveBeenCalledTimes(2);
    expect(browser.diagnostics.discovery).toBe('DevToolsActivePort');
    await browser.stop();
  });

  it('reports a spawn error without retrying or waiting for the full deadline', async () => {
    const options = fixture({ onStart: child => child.emit('error', Object.assign(new Error('not executable'), { code: 'EACCES' })) });
    const onAttempt = vi.fn();
    await expect(launchIsolatedChrome({ ...options, onAttempt })).rejects.toMatchObject({
      diagnostics: { state: 'spawn-error', spawnError: 'EACCES: not executable' },
    });
    expect(options.spawnProcess).toHaveBeenCalledOnce(); expect(onAttempt).toHaveBeenCalledOnce();
    expect(options.children[0].kill).toHaveBeenCalledOnce();
  });

  it('retains fatal stderr and an early exit code instead of an opaque startup timeout', async () => {
    const options = fixture({ onStart: child => {
      child.stderr.write('fixture: missing shared library\n'); child.emit('exit', 127, null); child.emit('close', 127, null);
    } });
    await expect(launchIsolatedChrome(options)).rejects.toMatchObject({ diagnostics: {
      state: 'early-exit', exitCode: 127, stderr: 'fixture: missing shared library\n',
    } });
    expect(options.spawnProcess).toHaveBeenCalledOnce();
  });

  it('bounds a hung HTTP readiness request and reaps the still-running process', async () => {
    const options = fixture({ readPortFile: async () => '43210\n', request: vi.fn(() => new Promise(() => {})), timeoutMs: 70 });
    const started = performance.now();
    await expect(startChromeAttempt(options)).rejects.toMatchObject({ diagnostics: {
      state: 'readiness-timeout', lastReadinessError: 'Error: DevTools readiness request timed out',
    } });
    expect(performance.now() - started).toBeLessThan(2000);
    expect(options.children[0].kill).toHaveBeenCalledOnce();
  });

  it('never follows a non-loopback endpoint printed by a failed process', async () => {
    const options = fixture({ onStart: child => child.stderr.write('DevTools listening on ws://outside.invalid:43210/devtools/browser/test\n'), timeoutMs: 60 });
    await expect(startChromeAttempt(options)).rejects.toMatchObject({ diagnostics: { state: 'readiness-timeout' } });
    expect(options.request).not.toHaveBeenCalled();
  });

  it('rejects a listener that does not identify the same local CDP browser', async () => {
    const options = fixture({ readPortFile: async () => '43210\n', timeoutMs: 60 });
    options.request.mockResolvedValue({ ok: true, json: async () => ({ ...version,
      webSocketDebuggerUrl: 'ws://outside.invalid:43210/devtools/browser/test' }) });
    await expect(startChromeAttempt(options)).rejects.toMatchObject({ diagnostics: {
      state: 'readiness-timeout', lastReadinessError: 'Error: Invalid local DevTools version response',
    } });
  });

  it('keeps bounded diagnostic tails with the final failure message', async () => {
    const options = fixture({ onStart: child => {
      child.stderr.write('x'.repeat(20000) + '\nfixture-final-error'); child.emit('exit', 1, null); child.emit('close');
    } });
    const error = await startChromeAttempt(options).catch(error => error);
    expect(error.diagnostics.stderr.length).toBe(16384);
    expect(error.diagnostics.stderr).toMatch(/fixture-final-error$/);
  });

  it('retries only a live readiness timeout, with a fresh profile and retained first-attempt evidence', async () => {
    const options = fixture({ timeoutMs: 300 });
    const children = [];
    options.spawnProcess = vi.fn(() => {
      const attempt = children.length;
      const child = processFixture(child => { if (attempt === 1) child.stderr.write(`DevTools listening on ${version.webSocketDebuggerUrl}\n`); });
      children.push(child); return child;
    });
    const observations = [];
    const browser = await launchIsolatedChrome({ ...options, onAttempt: attempts => observations.push(structuredClone(attempts)) });
    expect(browser.attempts.map(attempt => attempt.state)).toEqual(['readiness-timeout', 'ready']);
    expect(observations).toHaveLength(2);
    expect(options.spawnProcess.mock.calls[1][1]).toContain('--user-data-dir=/tmp/isolated-fixture-retry');
    expect(children[0].kill).toHaveBeenCalledOnce(); expect(children[1].kill).not.toHaveBeenCalled();
    await browser.stop(); expect(children[1].kill).toHaveBeenCalledOnce();
  });

  it('fails after exactly two startup timeouts and cleans both processes', async () => {
    const options = fixture({ timeoutMs: 40 }); const observations = [];
    await expect(launchIsolatedChrome({ ...options, onAttempt: attempts => observations.push(structuredClone(attempts)) }))
      .rejects.toMatchObject({ diagnostics: { state: 'readiness-timeout' } });
    expect(options.spawnProcess).toHaveBeenCalledTimes(2);
    expect(observations.at(-1).map(attempt => attempt.state)).toEqual(['readiness-timeout', 'readiness-timeout']);
    for (const child of options.children) expect(child.kill).toHaveBeenCalledOnce();
  });

  it('cleans an otherwise ready browser if preserving evidence fails', async () => {
    const options = fixture({ readPortFile: async () => '43210\n' });
    await expect(launchIsolatedChrome({ ...options, onAttempt: () => { throw new Error('fixture disk write failed'); } }))
      .rejects.toThrow('fixture disk write failed');
    expect(options.children[0].kill).toHaveBeenCalledOnce();
    expect(options.spawnProcess).toHaveBeenCalledOnce();
  });

  it('fails closed without launching another browser if the owned process cannot be reaped', async () => {
    const options = fixture({ timeoutMs: 30, cleanupTimeoutMs: 10 });
    options.spawnProcess = vi.fn(() => {
      const child = processFixture(); child.kill = vi.fn(() => true); return child;
    });
    await expect(launchIsolatedChrome(options)).rejects.toMatchObject({ diagnostics: {
      state: 'cleanup-failed', cleanupState: 'failed',
    } });
    expect(options.spawnProcess).toHaveBeenCalledOnce();
  });

  it('captures stderr and the exit code from an actual native child process', async () => {
    const options = fixture({ timeoutMs: 2000,
      spawnProcess: () => spawn(process.execPath, ['-e', 'process.stderr.write("native startup fixture failure\\n");process.exitCode=42;'],
        { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] }),
    });
    await expect(startChromeAttempt(options)).rejects.toMatchObject({ diagnostics: {
      state: 'early-exit', exitCode: 42, stderr: 'native startup fixture failure\n', cleanupState: 'closed',
    } });
  });

  it('owns and reaps the detached POSIX process group even after its launcher exits', async () => {
    let groupAlive = true;
    const signalGroup = vi.fn((pid, signal) => {
      expect(pid).toBe(1234);
      if (!groupAlive) throw Object.assign(new Error('gone'), { code: 'ESRCH' });
      if (signal === 'SIGTERM') groupAlive = false;
      return true;
    });
    const options = fixture({ platform: 'linux', signalGroup, onStart: child => {
      child.emit('exit', 0, null); child.emit('close', 0, null);
    } });
    await expect(launchIsolatedChrome(options)).rejects.toMatchObject({ diagnostics: {
      state: 'early-exit', exitCode: 0, cleanupState: 'closed', processGroup: 'owned detached group',
    } });
    expect(options.spawnProcess.mock.calls[0][2].detached).toBe(true);
    expect(signalGroup).toHaveBeenCalledWith(1234, 'SIGTERM');
    expect(options.children[0].kill).not.toHaveBeenCalled();
    expect(options.spawnProcess).toHaveBeenCalledOnce();
  });

  it('does not retry a timed-out POSIX launch if its owned group survives termination', async () => {
    const options = fixture({ platform: 'linux', timeoutMs: 30, cleanupTimeoutMs: 10,
      signalGroup: vi.fn(() => true), onStart: child => child.emit('close'),
    });
    await expect(launchIsolatedChrome(options)).rejects.toMatchObject({ diagnostics: {
      state: 'cleanup-failed', cleanupState: 'failed',
    } });
    expect(options.signalGroup).toHaveBeenCalledWith(1234, 'SIGKILL');
    expect(options.spawnProcess).toHaveBeenCalledOnce();
  });

  it('never signals an already reaped process group on repeated disposal', async () => {
    let groupAlive = true;
    const options = fixture({ platform: 'linux', readPortFile: async () => '43210\n' });
    options.signalGroup = vi.fn((pid, signal) => {
      expect(pid).toBe(1234);
      if (!groupAlive) throw Object.assign(new Error('gone'), { code: 'ESRCH' });
      if (signal === 'SIGTERM') { groupAlive = false; options.children[0].emit('close'); }
      return true;
    });
    const browser = await startChromeAttempt(options);
    await browser.stop(); const signals = options.signalGroup.mock.calls.length;
    await browser.stop(); expect(options.signalGroup).toHaveBeenCalledTimes(signals);
  });
});
