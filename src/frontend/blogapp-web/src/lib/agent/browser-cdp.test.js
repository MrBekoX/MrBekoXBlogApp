import { EventEmitter } from 'node:events';
import { describe, expect, it, vi } from 'vitest';
import { Cdp, connectCdp } from '../../../tools/agent-cdp.mjs';

function socketFixture() {
  return Object.assign(new EventEmitter(), { send: vi.fn(), close: vi.fn() });
}

describe('browser acceptance CDP failure bounds', () => {
  it('rejects all in-flight commands when the browser disconnects', async () => {
    const socket = socketFixture(); const cdp = new Cdp(socket);
    const commands = [cdp.send('Page.enable'), cdp.evaluate('true')];
    const settled = Promise.allSettled(commands); socket.emit('close');
    expect((await settled).map(result => result.status)).toEqual(['rejected', 'rejected']);
    expect(cdp.pending.size).toBe(0);
    await expect(cdp.send('Page.enable')).rejects.toThrow('transport closed');
  });

  it('rejects pending commands on a socket error with the cause visible', async () => {
    const socket = socketFixture(); const cdp = new Cdp(socket);
    const command = cdp.send('Page.enable'); socket.emit('error', new Error('fixture browser died'));
    await expect(command).rejects.toThrow('fixture browser died'); expect(cdp.pending.size).toBe(0);
  });

  it('bounds a browser command that never answers', async () => {
    const socket = socketFixture(); const cdp = new Cdp(socket, 30);
    await expect(cdp.evaluate('fixture')).rejects.toThrow('Runtime.evaluate timed out after 30ms');
    expect(cdp.pending.size).toBe(0); cdp.close();
  });

  it('returns a real command reply and clears its timer', async () => {
    const socket = socketFixture(); const cdp = new Cdp(socket, 30);
    const command = cdp.evaluate('fixture');
    socket.emit('message', JSON.stringify({ id: 1, result: { result: { value: 'answer' } } }));
    await expect(command).resolves.toBe('answer'); expect(cdp.pending.size).toBe(0); cdp.close();
  });

  it('bounds the initial socket connection and closes only its own socket', async () => {
    const socket = socketFixture(); const WebSocket = vi.fn(function () { return socket; });
    await expect(connectCdp(WebSocket, 'ws://127.0.0.1:1234/devtools/page/test', 30))
      .rejects.toThrow('connection timed out after 30ms');
    expect(socket.close).toHaveBeenCalledOnce();
  });

  it('reports an initial browser socket failure immediately', async () => {
    const socket = socketFixture(); const WebSocket = vi.fn(function () { return socket; });
    const connection = connectCdp(WebSocket, 'ws://127.0.0.1:1234/devtools/page/test');
    socket.emit('error', new Error('ECONNREFUSED'));
    await expect(connection).rejects.toThrow('ECONNREFUSED'); expect(socket.close).toHaveBeenCalledOnce();
  });

  it('ignores queued events from a disposed socket instead of calling stale target callbacks', () => {
    const socket = socketFixture(); const cdp = new Cdp(socket);
    const callback = vi.fn(); cdp.on('Fetch.requestPaused', callback); cdp.close();
    socket.emit('message', JSON.stringify({ method: 'Fetch.requestPaused', params: { requestId: 'old-target' } }));
    expect(callback).not.toHaveBeenCalled(); expect(cdp.events.size).toBe(0);
  });

  it.each(['ws://outside.invalid:1234/devtools/page/test', 'ws://127.0.0.1:9876/devtools/page/test'])(
    'rejects a CDP target outside the isolated browser: %s', async url => {
      const WebSocket = vi.fn();
      await expect(connectCdp(WebSocket, url, 30, 'http://127.0.0.1:1234'))
        .rejects.toThrow('same isolated loopback browser');
      expect(WebSocket).not.toHaveBeenCalled();
    });
});
