import { describe, expect, it } from 'vitest';
import { sitemapLastModified, staticSitemapPages } from './sitemap-entries';

describe('sitemapLastModified', () => {
  const now = new Date('2026-10-10T00:00:00.000Z');

  it('uses updatedAt when the API sends it', () => {
    expect(
      sitemapLastModified(
        { slug: 'a', updatedAt: '2026-02-02T00:00:00.000Z', publishedAt: '2026-01-01T00:00:00.000Z' },
        now,
      ).toISOString(),
    ).toBe('2026-02-02T00:00:00.000Z');
  });

  it('falls back to publishedAt when updatedAt is absent', () => {
    expect(
      sitemapLastModified(
        { slug: 'a', publishedAt: '2026-01-01T00:00:00.000Z', createdAt: '2025-01-01T00:00:00.000Z' },
        now,
      ).toISOString(),
    ).toBe('2026-01-01T00:00:00.000Z');
  });

  it('ignores an unparseable date instead of emitting Invalid Date', () => {
    expect(sitemapLastModified({ slug: 'a', updatedAt: 'not-a-date' }, now).toISOString()).toBe(
      now.toISOString(),
    );
  });
});

describe('staticSitemapPages', () => {
  const now = new Date('2026-10-22T00:00:00.000Z');

  it('ana sayfa, yazılar ve /about (Who am I) sayfalarını içerir', () => {
    const urls = staticSitemapPages('https://mrbekox.dev', now).map((entry) => entry.url);
    expect(urls).toEqual(['https://mrbekox.dev', 'https://mrbekox.dev/posts', 'https://mrbekox.dev/about']);
  });

  it('karşılıksız /#about anchor bağlantısı sitemap içine girmez', () => {
    const urls = staticSitemapPages('https://mrbekox.dev', now).map((entry) => entry.url);
    expect(urls.some((url) => url.includes('#'))).toBe(false);
  });
});
