import { redirect } from 'next/navigation';

interface ViewPageProps {
  searchParams: Promise<{ slug?: string }>;
}

/**
 * Legacy route redirect: /posts/view?slug=xxx -> /posts/xxx
 * Preserves backward compatibility for old URLs
 */
export default async function ViewRedirectPage({ searchParams }: ViewPageProps) {
  const params = await searchParams;
  const slug = params.slug;
  
  if (slug) {
    redirect(`/posts/${slug}`);
  }
  
  redirect('/posts');
}
