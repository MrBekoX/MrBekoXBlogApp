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
