import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { buildContentSecurityPolicy, buildMermaidRendererSecurityPolicy, SONNER_STYLE_HASH, EMPTY_STYLE_HASH } from './content-security-policy';

const NONCE = Buffer.from('test-nonce-128bit').toString('base64');
const directive = (policy: string, name: string) => policy.split('; ').find((item) => item.startsWith(name + ' '));

describe('production HTML CSP', () => {
  it('requires a nonce for inline scripts and style elements without eval', () => {
    const policy = buildContentSecurityPolicy(NONCE, { development: false });
    expect(directive(policy, 'script-src')).toContain("'nonce-" + NONCE + "'");
    expect(directive(policy, 'script-src')).toContain("'strict-dynamic'");
    expect(directive(policy, 'script-src')).not.toContain('unsafe-inline');
    expect(directive(policy, 'script-src')).not.toContain('unsafe-eval');
    expect(directive(policy, 'script-src-attr')).toBe("script-src-attr 'none'");
    expect(directive(policy, 'style-src')).not.toContain('unsafe-inline');
    expect(directive(policy, 'style-src')).toContain("'nonce-" + NONCE + "'");
    expect(directive(policy, 'style-src-attr')).toBe("style-src-attr 'unsafe-inline'");
  });

  it('permits only configured API and SignalR origins, including their WebSocket equivalents', () => {
    const policy = buildContentSecurityPolicy(NONCE, {
      development: false,
      siteUrl: 'https://blog.example.com',
      apiUrl: 'https://api.example.com/api/v1',
      signalRUrl: 'https://events.example.com',
    });
    const connect = directive(policy, 'connect-src')!;
    expect(connect).toContain('https://api.example.com');
    expect(connect).toContain('wss://api.example.com');
    expect(connect).toContain('https://events.example.com');
    expect(connect).toContain('wss://events.example.com');
    expect(connect.split(' ')).not.toContain('http:');
    expect(connect.split(' ')).not.toContain('https:');
    expect(connect.split(' ')).not.toContain('ws:');
    expect(connect.split(' ')).not.toContain('wss:');
  });

  it('ignores relative URLs and invalid or credential-bearing configuration', () => {
    const policy = buildContentSecurityPolicy(NONCE, {
      development: false, apiUrl: '/api/v1', signalRUrl: 'https://user:secret@example.com', siteUrl: 'javascript:alert(1)',
    });
    expect(directive(policy, 'connect-src')).toBe("connect-src 'self'");
  });

  it('allows Cloudflare only for explicit future widget configuration', () => {
    const disabled = buildContentSecurityPolicy(NONCE, { development: false });
    const enabled = buildContentSecurityPolicy(NONCE, { development: false, turnstileConfigured: true });
    expect(disabled).not.toContain('challenges.cloudflare.com');
    expect(directive(disabled, 'frame-src')).toBe("frame-src 'self'");
    for (const name of ['script-src', 'connect-src', 'frame-src']) {
      expect(directive(enabled, name)).toContain('https://challenges.cloudflare.com');
    }
    expect(directive(enabled, 'script-src')).not.toContain('unsafe-inline');
  });

  it('restricts debugging allowances to development', () => {
    const dev = buildContentSecurityPolicy(NONCE, { development: true });
    expect(directive(dev, 'script-src')).toContain("'unsafe-eval'");
    expect(directive(dev, 'connect-src')).toContain('ws://localhost:*');
    expect(directive(buildContentSecurityPolicy(NONCE, { development: false }), 'connect-src')).not.toContain('*');
  });

  it('rejects nonce header injection', () => {
    expect(() => buildContentSecurityPolicy("bad' 'unsafe-inline", { development: false })).toThrow();
  });

  it('authorizes only the exact pinned trusted Sonner stylesheet', () => {
    const source = readFileSync('node_modules/sonner/dist/index.mjs', 'utf8');
    const literal = source.match(/__insertCSS\(("(?:[^"\\]|\\.)*")\)/)?.[1];
    expect(literal, 'The trusted library stylesheet must be identifiable').toBeTruthy();
    const hash = createHash('sha256').update(JSON.parse(literal!)).digest('base64');
    expect(SONNER_STYLE_HASH).toBe("'sha256-" + hash + "'");
    expect(EMPTY_STYLE_HASH).toBe("'sha256-" + createHash('sha256').update('').digest('base64') + "'");
    expect(directive(buildContentSecurityPolicy(NONCE, { development: false }), 'style-src')).toContain(SONNER_STYLE_HASH);
  });

  it('confines Mermaid CSS allowance to a script-nonced opaque sandbox without network access', () => {
    const policy = buildMermaidRendererSecurityPolicy(NONCE);
    expect(directive(policy, 'sandbox')).toBe('sandbox allow-scripts');
    expect(directive(policy, 'connect-src')).toBe("connect-src 'none'");
    expect(directive(policy, 'frame-src')).toBe("frame-src 'none'");
    expect(directive(policy, 'frame-ancestors')).toBe("frame-ancestors 'self'");
    expect(directive(policy, 'style-src')).toBe("style-src 'unsafe-inline'");
    expect(directive(policy, 'script-src')).toContain("'nonce-" + NONCE + "'");
    expect(directive(policy, 'script-src')).not.toContain('unsafe-inline');
    expect(directive(policy, 'script-src')).not.toContain('unsafe-eval');
  });
});
