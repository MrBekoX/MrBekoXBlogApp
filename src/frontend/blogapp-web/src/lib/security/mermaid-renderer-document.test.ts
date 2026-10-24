import { describe, expect, it } from 'vitest';
import { runInNewContext } from 'node:vm';
import { mermaidRendererDocument } from './mermaid-renderer-document';

const NONCE = Buffer.from('test-nonce-128bit').toString('base64');

describe('isolated Mermaid document delivery', () => {
  it('uses the versioned external asset for public production documents', () => {
    const document = mermaidRendererDocument(NONCE, '12.1.0');
    expect(document).toContain('nonce="' + NONCE + '" src="/mermaid-renderer/mermaid.js?v=12.1.0"');
    expect(document).not.toContain('atob(');
  });

  it('decodes trusted local bytes without interpolating script terminators or losing UTF-8', () => {
    const trustedSource = 'window.label="</script><script>untrusted()</script> — ✓";';
    const document = mermaidRendererDocument(NONCE, '12.1.0', Buffer.from(trustedSource).toString('base64'));
    expect(document).not.toContain(trustedSource);
    expect(document).not.toContain('src="/mermaid-renderer/mermaid.js');
    const loader = document.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)?.[1];
    expect(loader).toBeTruthy();
    let inserted: { nonce?: string; textContent?: string } | undefined;
    runInNewContext(loader!, {
      document: {
        currentScript: { nonce: NONCE },
        createElement: () => ({}),
        head: { appendChild: (script: typeof inserted) => { inserted = script; } },
      },
      atob, TextDecoder, Uint8Array,
    });
    expect(inserted).toEqual({ nonce: NONCE, textContent: trustedSource });
  });

  it('rejects values that could escape trusted document metadata', () => {
    expect(() => mermaidRendererDocument(NONCE, '12.1.0', '</script>')).toThrow();
    expect(() => mermaidRendererDocument('bad"', '12.1.0')).toThrow();
    expect(() => mermaidRendererDocument(NONCE, '12.1.0"')).toThrow();
  });
});
