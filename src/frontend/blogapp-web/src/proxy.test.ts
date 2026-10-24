import { describe, expect, it } from 'vitest';
import { NextRequest } from 'next/server';
// Next 16.1 retains the legacy helper name for the proxy matcher.
import { unstable_doesMiddlewareMatch } from 'next/experimental/testing/server';
import { config, proxy } from './proxy';

describe('trusted HTML nonce proxy', () => {
  it('overwrites client-supplied nonce and CSP metadata with one fresh server value', () => {
    const request = new NextRequest('https://example.com/mrbekox-console', { headers: {
      'x-nonce': 'client-controlled',
      'Content-Security-Policy': "script-src 'unsafe-inline'",
    } });
    const first = proxy(request);
    const second = proxy(request);
    const firstNonce = first.headers.get('x-middleware-request-x-nonce');
    expect(firstNonce).toMatch(/^[A-Za-z0-9+/]{22}==$/);
    expect(firstNonce).not.toBe('client-controlled');
    expect(firstNonce).not.toBe(second.headers.get('x-middleware-request-x-nonce'));
    const policy = first.headers.get('Content-Security-Policy');
    expect(policy).toContain("'nonce-" + firstNonce + "'");
    expect(first.headers.get('x-middleware-request-content-security-policy')).toBe(policy);
    expect(first.headers.get('Cache-Control')).toContain('no-store');
  });

  it('covers HTML and unknown routes while leaving API, hubs, and immutable assets alone', () => {
    for (const url of ['/', '/mrbekox-console', '/login', '/about', '/unknown-page', '/iconXpng', '/mermaid-renderer']) {
      expect(unstable_doesMiddlewareMatch({ config, nextConfig: {}, url }), url).toBe(true);
    }
    for (const url of ['/api/v1/auth/login', '/hubs/agent-runs', '/uploads/image.webp', '/_next/static/chunk.js', '/icon.png', '/robots.txt', '/rss', '/mermaid-renderer/mermaid.js']) {
      expect(unstable_doesMiddlewareMatch({ config, nextConfig: {}, url }), url).toBe(false);
    }
  });

  it('uses a separate sandbox policy and framing exception for the exact renderer document', () => {
    const frame = proxy(new NextRequest('https://example.com/mermaid-renderer'));
    expect(frame.headers.get('Content-Security-Policy')).toContain('sandbox allow-scripts');
    expect(frame.headers.get('Content-Security-Policy')).toContain("frame-ancestors 'self'");
    expect(frame.headers.get('X-Frame-Options')).toBe('SAMEORIGIN');
    const page = proxy(new NextRequest('https://example.com/about'));
    expect(page.headers.get('X-Frame-Options')).toBe('DENY');
    expect(page.headers.get('Content-Security-Policy')).toContain("frame-ancestors 'none'");
    expect(page.headers.get('Content-Security-Policy')).not.toContain('sandbox');
  });
});
