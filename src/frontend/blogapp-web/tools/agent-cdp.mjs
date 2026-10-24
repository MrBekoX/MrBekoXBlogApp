/** Bounded CDP transport: a dead browser must fail acceptance, never hang it. */
export class Cdp {
  constructor(socket, timeoutMs = 5000) {
    this.socket = socket; this.timeoutMs = timeoutMs; this.next = 0;
    this.pending = new Map(); this.events = new Map(); this.closed = false;
    socket.on('message', bytes => {
      if (this.closed) return;
      let message;
      try { message = JSON.parse(bytes.toString()); }
      catch { this.fail(new Error('Invalid CDP JSON response')); return; }
      if (message.id) {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id); clearTimeout(pending.timer);
        if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
        else pending.resolve(message.result);
      } else for (const callback of this.events.get(message.method) ?? []) callback(message.params);
    });
    socket.on('close', () => this.fail(new Error('CDP socket closed')));
    socket.on('error', error => this.fail(new Error(`CDP socket error: ${error.message}`)));
  }
  fail(error) {
    this.closed = true;
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(error); }
    this.pending.clear(); this.events.clear();
  }
  on(name, callback) { this.events.set(name, [...this.events.get(name) ?? [], callback]); }
  send(method, params = {}, timeoutMs = this.timeoutMs) {
    if (this.closed) return Promise.reject(new Error(`CDP transport closed before ${method}`));
    return new Promise((resolve, reject) => {
      const id = ++this.next;
      const timer = setTimeout(() => { this.pending.delete(id);
        reject(new Error(`CDP ${method} timed out after ${timeoutMs}ms`)); }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      try { this.socket.send(JSON.stringify({ id, method, params })); }
      catch (error) { this.pending.delete(id); clearTimeout(timer); reject(error); }
    });
  }
  async evaluate(expression, timeoutMs) {
    const result = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }, timeoutMs);
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
  close() { this.fail(new Error('CDP transport disposed')); this.socket.close(); }
}

export async function connectCdp(WebSocket, url, timeoutMs = 5000, expectedOrigin) {
  const endpoint = new URL(url);
  if (endpoint.protocol !== 'ws:' || !['127.0.0.1', '[::1]'].includes(endpoint.hostname)
    || !endpoint.port || endpoint.username || endpoint.password || endpoint.search || endpoint.hash
    || !/^\/devtools\/(?:page|browser)\//.test(endpoint.pathname)
    || (expectedOrigin && endpoint.host !== new URL(expectedOrigin).host)) {
    throw new Error('CDP endpoint must belong to the same isolated loopback browser');
  }
  const socket = new WebSocket(url);
  await new Promise((resolve, reject) => {
    const finish = error => {
      clearTimeout(timer);
      socket.off('open', opened); socket.off('error', failed); socket.off('close', closed);
      if (error) { socket.on('error', () => {}); socket.close(); reject(error); }
      else resolve();
    };
    const opened = () => finish();
    const failed = error => finish(new Error(`CDP connection failed: ${error.message}`));
    const closed = () => finish(new Error('CDP socket closed before connecting'));
    const timer = setTimeout(() => finish(new Error(`CDP connection timed out after ${timeoutMs}ms`)), timeoutMs);
    socket.once('open', opened); socket.once('error', failed); socket.once('close', closed);
  });
  return new Cdp(socket, timeoutMs);
}
