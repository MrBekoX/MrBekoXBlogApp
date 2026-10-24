/**
 * Real Chrome + React + Axios + SignalR-client acceptance, with a loopback-only
 * HTTP/SignalR JSON fixture. No application server, database, .env or provider
 * credentials are used. Build/cache/browser-profile artifacts stay in OS temp.
 * Run: npm run test:agent-browser (CHROME_BIN may select an installed browser).
 */
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import http from 'node:http';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { launchIsolatedChrome } from './isolated-chrome.mjs';
import { connectCdp } from './agent-cdp.mjs';

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(webRoot, 'package.json'));
const { build } = await import(pathToFileURL(require.resolve('vite')).href);
const ws = require('ws');
const WebSocket = ws.WebSocket ?? ws;
const WebSocketServer = ws.WebSocketServer ?? ws.Server;
const temp = await mkdtemp(path.join(os.tmpdir(), 'codex-agent-browser-'));
const out = path.join(temp, 'dist');
const profile = path.join(temp, 'chrome-profile');
const candidates = [process.env.CHROME_BIN, 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/opt/google/chrome/chrome'];
const chromeBin = candidates.find(candidate => candidate && existsSync(candidate));
assert(chromeBin, 'Install Chrome/Chromium or provide CHROME_BIN; browser acceptance must not silently skip.');

await build({ configFile: false, root: temp, envDir: temp, cacheDir: path.join(temp, 'vite-cache'),
  esbuild: { jsx: 'automatic', jsxImportSource: 'react' },
  logLevel: 'error', define: { 'process.env': JSON.stringify({ NODE_ENV: 'production',
    NEXT_PUBLIC_API_URL: '/api/v1', NEXT_PUBLIC_SIGNALR_URL: '' }) },
  resolve: { alias: [{ find: '@', replacement: path.join(webRoot, 'src') },
    { find: /^react$/, replacement: require.resolve('react') },
    { find: /^react\/jsx-runtime$/, replacement: require.resolve('react/jsx-runtime') },
    { find: /^react-dom\/client$/, replacement: require.resolve('react-dom/client') }] },
  build: { outDir: out, emptyOutDir: true, minify: false,
    rollupOptions: { input: path.join(webRoot, 'tools/agent-browser-harness.tsx'),
      output: { entryFileNames: 'harness.js', format: 'es' } } } });

const RUN = '11111111-1111-4111-8111-111111111111';
const nonce = 'bG9jYWwtYWNjZXB0YW5jZQ==';
let current;
let browser;
let cdp;
const results = [];
const clients = new Set();
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
function context(name) { return { name, runId: RUN, phase: name === 'restore_research' ? 'Failed' : 'Accepted', seq: 1,
  posts: [], gets: 0, failGets: 0, events: [], subscribed: 0, reconnectRejected: false,
  collected: 0, timers: [], sockets: new Set(), until: null, readyTerminal: false }; }
function later(ctx, ms, action) { ctx.timers.push(setTimeout(action, ms)); }
function accepted(ctx) { return { runId: ctx.runId, conversationId: 'browser-conversation', turnSequence: 1,
  replay: false, acceptedAt: new Date().toISOString(), deadlineAt: new Date(Date.now() + 60000).toISOString() }; }
function status(ctx) { return { ...accepted(ctx), status: ctx.phase, lastEventSequence: ctx.seq,
  modePreference: ctx.name === 'restore_research' ? 'deep_research' : 'auto', selectedMode: 'fast',
  question: 'Please explain this article.', language: 'en', conversationTopic: 'auto',
  isProvisionalTerminal: ctx.until !== null && Date.now() < ctx.until,
  reconciliationUntil: ctx.until === null ? null : new Date(ctx.until).toISOString(),
  reconciliationRemainingSeconds: ctx.until === null ? 0 : Math.max(Math.ceil((ctx.until - Date.now()) / 1000), 0),
  result: ctx.phase === 'Accepted' ? null : { status: ctx.phase.toLowerCase(), citations: [],
    answer: ctx.phase === 'Completed'
      ? `Verified queue guidance. ![source](/collect?message=acceptance-private-canary)` : null } }; }
function notify(ctx) { for (const socket of ctx.sockets) if (socket.subscribed && socket.readyState === WebSocket.OPEN)
  socket.send(JSON.stringify({ type: 1, target: 'RunUpdated', arguments: [{ run_id: ctx.runId, event_sequence: ctx.seq }] }) + '\x1e'); }
function complete(ctx) { ctx.phase = 'Completed'; ctx.seq += 1; ctx.until = null;
  ctx.events.push({ eventSequence: ctx.seq, messageId: randomUUID(), messageType: 'agent.run.completed', occurredAt: new Date().toISOString() });
  notify(ctx); }
function json(res, code, data) { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); }
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const ctx = current;
  if (url.pathname === '/harness.js') { res.writeHead(200, { 'Content-Type': 'text/javascript' }); res.end(await readFile(path.join(out, 'harness.js'))); return; }
  if (url.pathname === '/') {
    const seed = ctx.name === 'restore_research' ? `localStorage.setItem('acceptance-${ctx.name}','${RUN}');` : '';
    res.writeHead(200, { 'Content-Type': 'text/html', 'Content-Security-Policy':
      `default-src 'self'; script-src 'self' 'nonce-${nonce}'; img-src 'self' http: https: data:; connect-src 'self' ws:; style-src 'unsafe-inline'` });
    res.end(`<html><body><div id="root"></div><script nonce="${nonce}">${seed}</script><script nonce="${nonce}" type="module" src="/harness.js"></script></body></html>`); return;
  }
  if (url.pathname === '/collect') { ctx.collected += 1; res.writeHead(204); res.end(); return; }
  if (url.pathname.endsWith('/negotiate')) { json(res, 200, { negotiateVersion: 1, connectionId: randomUUID(),
    connectionToken: randomUUID(), availableTransports: [{ transport: 'WebSockets', transferFormats: ['Text'] }] }); return; }
  if (url.pathname.includes('csrf')) { json(res, 200, { success: true, data: { token: 'browser-fixture-only' } }); return; }
  if (req.method === 'POST' && ['/api/v1/agent/messages', '/api/v1/agent/research'].includes(url.pathname)) {
    let body = ''; for await (const chunk of req) body += chunk;
    ctx.posts.push({ path: url.pathname, body: JSON.parse(body) });
    if (ctx.name === 'restore_research') ctx.runId = '22222222-2222-4222-8222-222222222222';
    ctx.phase = 'Accepted'; ctx.events = []; ctx.seq = 1;
    if (ctx.name.startsWith('provisional')) { ctx.phase = 'Failed'; ctx.seq = 2;
      ctx.until = Date.now() + (['provisional_expiry', 'provisional_final_offline'].includes(ctx.name) ? 1000 : 10000); }
    json(res, 202, { success: true, data: accepted(ctx) });
    if (!ctx.name.startsWith('provisional')) later(ctx, ctx.name === 'reconnect' ? 5000 : 500, () => complete(ctx));
    return;
  }
  if (url.pathname === `/api/v1/agent/runs/${ctx.runId}/events`) { const after = Number(url.searchParams.get('after') ?? 0);
    json(res, 200, { success: true, data: { runId: ctx.runId, runStatus: ctx.phase, lastEventSequence: ctx.seq,
      events: ctx.events.filter(event => event.eventSequence > after), hasMore: false } }); return; }
  if (url.pathname === `/api/v1/agent/runs/${ctx.runId}`) { ctx.gets += 1;
    if (ctx.name === 'provisional_final_offline' && Date.now() >= ctx.until && !ctx.allowFinalRead) {
      json(res, 503, { success: false, message: 'Injected final verification outage' }); return;
    }
    if (ctx.name === 'lost_terminal_get' && ctx.phase === 'Completed' && ctx.failGets++ === 0) {
      json(res, 503, { success: false, message: 'Injected temporary read failure' }); return;
    }
    json(res, 200, { success: true, data: status(ctx) }); return;
  }
  res.writeHead(404); res.end();
});
const wss = new WebSocketServer({ noServer: true });
server.on('upgrade', (req, socket, head) => wss.handleUpgrade(req, socket, head, ws => wss.emit('connection', ws, req)));
wss.on('connection', socket => {
  const ctx = current; ctx.sockets.add(socket); clients.add(socket);
  socket.on('close', () => { ctx.sockets.delete(socket); clients.delete(socket); });
  socket.on('message', bytes => {
    for (const frame of bytes.toString().split('\x1e').filter(Boolean)) {
      const message = JSON.parse(frame);
      if (message.protocol) { socket.send('{}\x1e'); continue; }
      if (message.type !== 1 || message.target !== 'SubscribeToRun') continue;
      ctx.subscribed += 1;
      if (ctx.name === 'reconnect' && ctx.subscribed === 2) {
        ctx.reconnectRejected = true;
        socket.send(JSON.stringify({ type: 3, invocationId: message.invocationId, error: 'Injected temporary membership failure' }) + '\x1e');
      } else {
        socket.subscribed = true;
        socket.send(JSON.stringify({ type: 3, invocationId: message.invocationId }) + '\x1e');
        if (ctx.name === 'reconnect' && ctx.subscribed === 1) later(ctx, 200, () => socket.terminate());
      }
    }
  });
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;

async function until(predicate, message, timeout = 15000) { const start = Date.now();
  while (Date.now() - start < timeout) { if (await predicate()) return; await wait(50); }
  let state = null;
  if (cdp) try { state = await cdp.evaluate('window.agentAcceptance ? {phase:window.agentAcceptance.phase,active:window.agentAcceptance.active,channel:window.agentAcceptance.channel} : null', 1000); }
  catch (error) { state = { diagnosticUnavailable: error.message }; }
  throw new Error(`Timed out: ${message}; ${JSON.stringify({ state, gets: current?.gets, posts: current?.posts, subscriptions: current?.subscribed })}`); }

try {
  console.log(`Chrome startup evidence: ${path.join(temp, 'chrome-startup.json')}`);
  browser = await launchIsolatedChrome({ executablePath: chromeBin, profilePath: profile,
    onAttempt: async attempts => {
      await writeFile(path.join(temp, 'chrome-startup.json'), JSON.stringify(attempts, null, 2));
      const latest = attempts.at(-1);
      console.log(`Chrome startup attempt ${latest.attempt}: ${JSON.stringify(latest)}`);
    } });
  const debuggingOrigin = browser.origin;
  const browserVersion = browser.version;
  const devToolsFetch = (pathname, options = {}) => fetch(`${debuggingOrigin}${pathname}`,
    { ...options, signal: AbortSignal.timeout(5000), redirect: 'error' });
  for (const name of ['normal', 'lost_terminal_get', 'reconnect', 'restore_research', 'provisional_recovery',
    'provisional_clock_skew', 'provisional_expiry', 'provisional_final_offline']) {
    console.log(`Browser acceptance: ${name}`);
    current = context(name);
    const ctx = current;
    const target = await (await devToolsFetch('/json/new?about:blank', { method: 'PUT' })).json();
    cdp = await connectCdp(WebSocket, target.webSocketDebuggerUrl, 5000, debuggingOrigin);
    await cdp.send('Page.enable'); await cdp.send('Runtime.enable');
    if (name === 'provisional_clock_skew') await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
      source: 'const realNow=Date.now.bind(Date); Date.now=()=>realNow()+600000;',
    });
    // Fail external requests before any socket can leave this loopback test.
    await cdp.send('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] });
    cdp.on('Fetch.requestPaused', event => {
      const allowed = event.request.url.startsWith(origin + '/') || event.request.url.startsWith('data:');
      const transport = cdp;
      void transport.send(allowed ? 'Fetch.continueRequest' : 'Fetch.failRequest', allowed
        ? { requestId: event.requestId } : { requestId: event.requestId, errorReason: 'BlockedByClient' })
        .catch(error => { if (!transport.closed) console.error(`CDP request interception failed: ${error.message}`); });
    });
    await cdp.send('Page.navigate', { url: `${origin}/?case=${name}` });
    await until(() => cdp.evaluate('Boolean(window.agentAcceptance)'), `${name}: real React mount`);
    if (name === 'restore_research') {
      await until(() => cdp.evaluate('window.agentAcceptance.phase === "failed"'), 'restored research');
      await cdp.evaluate('window.agentAcceptance.retry()');
      assert.equal(ctx.posts[0]?.path, '/api/v1/agent/research');
      assert.equal(ctx.posts.length, 1);
    } else await cdp.evaluate('window.agentAcceptance.submit()');
    if (name.startsWith('provisional')) {
      await until(() => cdp.evaluate('window.agentAcceptance.provisional'), `${name}: provisional state`);
      assert.equal(await cdp.evaluate('window.agentAcceptance.active'), true);
      assert.equal(await cdp.evaluate('document.querySelector("#retry").disabled'), true);
      if (['provisional_recovery', 'provisional_clock_skew'].includes(name)) complete(ctx);
    }
    const finalPhase = ['provisional_expiry', 'provisional_final_offline'].includes(name) ? 'failed' : 'completed';
    await until(() => cdp.evaluate(`window.agentAcceptance.phase === '${finalPhase}' && !window.agentAcceptance.active`), `${name}: terminal recovery`);
    assert.equal(await cdp.evaluate('Boolean(document.querySelector("#answer img, #answer source, #answer picture, link[rel=preload][as=image]"))'), false);
    await wait(150);
    assert.equal(ctx.collected, 0, 'model Markdown must not create automatic image requests');
    if (name === 'lost_terminal_get') assert(ctx.failGets >= 2 && ctx.gets >= 3);
    if (name === 'reconnect') assert(ctx.subscribed >= 3 && ctx.reconnectRejected);
    if (name === 'provisional_recovery') assert(ctx.subscribed >= 1, 'real SignalR membership must survive provisional failure');
    if (name === 'provisional_expiry') {
      await until(() => ctx.sockets.size === 0, 'bounded grace closes realtime subscription');
      const reads = ctx.gets; await wait(1200); assert.equal(ctx.gets, reads);
    }
    if (name === 'provisional_final_offline') {
      assert.equal(await cdp.evaluate('window.agentAcceptance.verificationUnavailable'), true);
      assert.match(await cdp.evaluate('document.querySelector("#unconfirmed").textContent'), /could|prevented|confirmation/i);
      await until(() => ctx.sockets.size === 0, 'unconfirmed result ends automatic realtime checks');
      const reads = ctx.gets; await wait(1200); assert.equal(ctx.gets, reads);
      ctx.allowFinalRead = true;
      await cdp.evaluate('window.agentAcceptance.checkFinal()');
      await until(() => cdp.evaluate('!window.agentAcceptance.verificationUnavailable'), 'manual authoritative final check');
      assert.equal(ctx.posts.length, 1, 'checking the final result must not resubmit the run');
    }
    results.push({ case: name, passed: true, phase: finalPhase, requests: ctx.gets,
      subscriptions: ctx.subscribed, automaticImages: ctx.collected });
    for (const timer of ctx.timers) clearTimeout(timer);
    await devToolsFetch(`/json/close/${target.id}`); cdp.close(); cdp = null;
    for (const socket of ctx.sockets) socket.terminate();
  }
  const report = { browser: browserVersion.Browser, startup: browser.attempts,
    evidence: 'Real browser, React effects, Axios and SignalR client; loopback fixture backend.',
    cases: results, liveProviderCalls: 0, deploy: false };
  await writeFile(path.join(temp, 'acceptance.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ passed: results.length, report: path.join(temp, 'acceptance.json') }));
} finally {
  cdp?.close();
  for (const socket of clients) socket.terminate();
  for (const timer of current?.timers ?? []) clearTimeout(timer);
  await new Promise(resolve => server.close(resolve)); wss.close();
  if (browser) {
    const final = await browser.stop();
    await writeFile(path.join(temp, 'chrome-final.json'), JSON.stringify(final, null, 2));
    if (results.length !== 8) console.error(`Chrome process at acceptance failure: ${JSON.stringify(final)}`);
  }
}
