import { afterEach, describe, expect, it, vi } from 'vitest';
import { GET } from './route';

const NONCE = Buffer.from('test-nonce-128bit').toString('base64');
const request = (host: string, extra: Record<string, string> = {}) => new Request('http://internal:3000/mermaid-renderer', {
  headers: { host, 'x-nonce': NONCE, ...extra },
});

afterEach(() => vi.unstubAllEnvs());

describe('Mermaid delivery selection with the actual pinned bundle', () => {
  it.each(['localhost:3000', 'preview.localhost:3000', '127.0.0.1:3000', '127.0.1.2:3000', '[::1]:3000'])('embeds trusted bytes for loopback %s', async (host) => {
    const response = await GET(request(host));
    expect(response.headers.get('Cache-Control')).toContain('no-store');
    expect(response.headers.get('X-Frame-Options')).toBe('SAMEORIGIN');
    const document = await response.text();
    expect(document).toContain('atob(');
    expect(document).not.toContain('src="/mermaid-renderer/mermaid.js');
  });

  it.each(['blog.example.com', 'localhost.example.com', '127.example.com', '127.0.0.1.example.com'])('keeps public %s on the cacheable external asset', async (host) => {
    const document = await (await GET(request(host, { 'x-forwarded-host': 'localhost:3000' }))).text();
    expect(document).toContain('src="/mermaid-renderer/mermaid.js?v=');
    expect(document).not.toContain('atob(');
  });

  it('keeps development usable with a custom development hostname', async () => {
    vi.stubEnv('NODE_ENV', 'development');
    expect(await (await GET(request('blog.test:3000'))).text()).toContain('atob(');
  });

  it('requires trusted request nonce metadata', async () => {
    expect((await GET(new Request('https://example.com/mermaid-renderer'))).status).toBe(500);
  });
});
