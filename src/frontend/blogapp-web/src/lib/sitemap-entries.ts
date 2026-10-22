import type { MetadataRoute } from 'next';

export interface SitemapPostFields {
  slug: string;
  updatedAt?: string | null;
  publishedAt?: string | null;
  createdAt?: string | null;
}

export function sitemapLastModified(post: SitemapPostFields, now = new Date()): Date {
  const raw = post.updatedAt || post.publishedAt || post.createdAt;
  if (!raw) return now;
  const date = new Date(raw);
  return Number.isNaN(date.getTime()) ? now : date;
}

/**
 * Statik (içerikten bağımsız) sayfalar. /about: yayımlanmış yazar profili ve
 * Who am I asistanı (gerçek sayfa; eski "/#about" karşılıksız bağlantısının yerine).
 */
export function staticSitemapPages(siteUrl: string, now = new Date()): MetadataRoute.Sitemap {
  return [
    {
      url: siteUrl,
      lastModified: now,
      changeFrequency: 'daily',
      priority: 1.0,
    },
    {
      url: `${siteUrl}/posts`,
      lastModified: now,
      changeFrequency: 'daily',
      priority: 0.9,
    },
    {
      url: `${siteUrl}/about`,
      lastModified: now,
      changeFrequency: 'monthly',
      priority: 0.7,
    },
  ];
}
