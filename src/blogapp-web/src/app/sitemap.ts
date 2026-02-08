import { MetadataRoute } from 'next';

// Dynamic sitemap for SSR mode
export const dynamic = 'force-dynamic';

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'https://mrbekox.dev';
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://mrbekox.dev/api/v1';

interface Post {
  slug: string;
  updatedAt: string;
}

interface ApiResponse<T> {
  items: T;
  success: boolean;
  message?: string;
}

async function getPosts(): Promise<Post[]> {
  try {
    // Fetch at build time for static export (no revalidation)
    const response = await fetch(`${API_URL}/posts?pageSize=1000&status=Published`, {
      cache: 'no-store'
    });
    
    if (!response.ok) {
      return [];
    }

    const data: ApiResponse<Post[]> = await response.json();
    return data.items || [];
  } catch {
    return [];
  }
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const posts = await getPosts();

  // Static pages
  const staticPages: MetadataRoute.Sitemap = [
    {
      url: SITE_URL,
      lastModified: new Date(),
      changeFrequency: 'daily',
      priority: 1.0,
    },
    {
      url: `${SITE_URL}/posts`,
      lastModified: new Date(),
      changeFrequency: 'daily',
      priority: 0.9,
    },
  ];

  // Dynamic blog post pages
  const postPages: MetadataRoute.Sitemap = posts.map((post) => ({
    url: `${SITE_URL}/posts/${post.slug}`,
    lastModified: new Date(post.updatedAt),
    changeFrequency: 'weekly' as const,
    priority: 0.8,
  }));

  return [...staticPages, ...postPages];
}
