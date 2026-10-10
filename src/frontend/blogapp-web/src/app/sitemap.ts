import { MetadataRoute } from 'next';
import { SITE_URL } from '@/lib/site-config';
import { fetchPosts } from '@/lib/server-api';
import { sitemapLastModified, type SitemapPostFields } from '@/lib/sitemap-entries';

export const dynamic = 'force-dynamic';

const SITEMAP_PAGE_SIZE = 100;
const SITEMAP_PAGE_CAP = 50;

async function getPublishedPosts(): Promise<SitemapPostFields[]> {
  const posts: SitemapPostFields[] = [];

  for (let pageNumber = 1; pageNumber <= SITEMAP_PAGE_CAP; pageNumber += 1) {
    const page = await fetchPosts({
      pageNumber,
      pageSize: SITEMAP_PAGE_SIZE,
      status: 'Published',
    });

    if (!page || page.items.length === 0) break;

    posts.push(...page.items);
    if (!page.hasNextPage) break;
  }

  return posts;
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const posts = await getPublishedPosts();
  const now = new Date();

  const staticPages: MetadataRoute.Sitemap = [
    {
      url: SITE_URL,
      lastModified: now,
      changeFrequency: 'daily',
      priority: 1.0,
    },
    {
      url: `${SITE_URL}/posts`,
      lastModified: now,
      changeFrequency: 'daily',
      priority: 0.9,
    },
  ];

  const postPages: MetadataRoute.Sitemap = posts.map((post) => ({
    url: `${SITE_URL}/posts/${post.slug}`,
    lastModified: sitemapLastModified(post, now),
    changeFrequency: 'weekly' as const,
    priority: 0.8,
  }));

  return [...staticPages, ...postPages];
}
