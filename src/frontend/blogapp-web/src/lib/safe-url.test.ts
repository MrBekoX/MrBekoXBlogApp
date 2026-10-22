import { describe, expect, it } from 'vitest';
import { safeChatLinkHref, safeExternalHttpUrl, sanitizeUrl } from './safe-url';

describe('sanitizeUrl (MarkdownRenderer davranışı korunur)', () => {
  it('http(s), kök-göreli, anchor ve şemasız göreli yolları geçirir', () => {
    expect(sanitizeUrl('https://example.com/a')).toBe('https://example.com/a');
    expect(sanitizeUrl('http://example.com')).toBe('http://example.com');
    expect(sanitizeUrl('/posts/x')).toBe('/posts/x');
    expect(sanitizeUrl('#bolum')).toBe('#bolum');
    expect(sanitizeUrl('./a.png')).toBe('./a.png');
    expect(sanitizeUrl('../a.png')).toBe('../a.png');
    expect(sanitizeUrl('image.png')).toBe('image.png');
  });

  it('tehlikeli şemaları (kodlanmış dahil) eler', () => {
    expect(sanitizeUrl('javascript:alert(1)')).toBeUndefined();
    expect(sanitizeUrl('JavaScript:alert(1)')).toBeUndefined();
    expect(sanitizeUrl('%6Aavascript:alert(1)')).toBeUndefined();
    expect(sanitizeUrl('data:text/html,<b>x</b>')).toBeUndefined();
    expect(sanitizeUrl('vbscript:x')).toBeUndefined();
    expect(sanitizeUrl('file:///etc/passwd')).toBeUndefined();
    expect(sanitizeUrl('mailto:a@b.c')).toBeUndefined();
    expect(sanitizeUrl(undefined)).toBeUndefined();
  });

  it('bozuk yüzde kodlaması render çökertmek yerine undefined döner', () => {
    expect(sanitizeUrl('%E0%A4%A')).toBeUndefined();
  });
});

describe('safeExternalHttpUrl', () => {
  it('yalnız mutlak http/https kabul eder', () => {
    expect(safeExternalHttpUrl('https://example.invalid/author')).toBe('https://example.invalid/author');
    expect(safeExternalHttpUrl('http://example.com')).toBe('http://example.com/');
  });

  it.each([
    'javascript:alert(1)',
    ' javascript:alert(1)',
    'data:text/html,x',
    '//evil.example',
    '/about#x',
    'ftp://example.com',
    'https://user:pass@example.com',
    'https://exa mple.com',
    'https://example.com/\nx',
    '',
    null,
    undefined,
  ])('reddeder: %s', (value) => {
    expect(safeExternalHttpUrl(value as string | null | undefined)).toBeNull();
  });
});

describe('safeChatLinkHref', () => {
  it('dış http(s) bağlantısını external olarak işaretler', () => {
    expect(safeChatLinkHref('https://mrbekox.dev')).toEqual({ href: 'https://mrbekox.dev/', external: true });
  });

  it('kök-göreli ve anchor bağlantıları dahili kabul eder', () => {
    expect(safeChatLinkHref('/about#education')).toEqual({ href: '/about#education', external: false });
    expect(safeChatLinkHref('#faq')).toEqual({ href: '#faq', external: false });
  });

  it.each(['javascript:alert(1)', 'data:x', '//evil.example/x', '/\\evil.example', 'relative/path', 'mailto:a@b.c'])(
    'reddeder: %s',
    (value) => {
      expect(safeChatLinkHref(value)).toBeNull();
    },
  );
});
