import { Metadata } from 'next';
import { fetchPosts } from '@/lib/server-api';
import { PostsListClient } from '@/components/posts/posts-list-client';
import { Sparkles } from 'lucide-react';

export const metadata: Metadata = {
  title: 'Yazılar',
  description: 'Yazılım geliştirme, teknoloji trendleri ve kişisel deneyimlerim hakkında yazdığım makaleler',
  openGraph: {
    title: 'Yazılar | MrBekoX Blog',
    description: 'Yazılım geliştirme, teknoloji trendleri ve kişisel deneyimlerim hakkında yazdığım makaleler',
  },
};

interface PostsPageProps {
  searchParams: Promise<{
    page?: string;
    search?: string;
    categoryId?: string;
    tagId?: string;
  }>;
}

export default async function PostsPage({ searchParams }: PostsPageProps) {
  const params = await searchParams;
  const page = params.page ? parseInt(params.page) : 1;
  const search = params.search || '';
  const categoryId = params.categoryId;
  const tagId = params.tagId;

  // Fetch initial posts on the server
  const initialPosts = await fetchPosts({
    pageNumber: page,
    pageSize: 9,
    status: 'Published',
    search: search || undefined,
    categoryId: categoryId,
    tagId: tagId,
  });

  return (
    <div className="relative min-h-screen">
      {/* Background decoration */}
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute top-0 right-1/4 w-96 h-96 bg-primary/5 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 left-1/4 w-80 h-80 bg-accent/10 rounded-full blur-3xl" />
      </div>

      {/* Hero Section */}
      <section className="border-b bg-gradient-to-br from-primary/5 via-background to-accent/5">
        <div className="container py-16 md:py-20">
          <div className="max-w-3xl mx-auto text-center space-y-6 animate-fade-in-up">
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 border border-primary/20 text-sm text-primary">
              <Sparkles className="w-4 h-4" />
              <span>Blog Yazıları</span>
            </div>
            
            <h1 className="text-4xl md:text-5xl font-bold tracking-tight font-serif">
              Yazılar &amp; Düşünceler
            </h1>
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
              Yazılım geliştirme, teknoloji trendleri ve kişisel deneyimlerim hakkında yazdığım makaleler
            </p>

            {/* Client Component for Search and Posts Grid */}
            <PostsListClient
              initialPosts={initialPosts}
              initialSearch={search}
              initialPage={page}
              categoryId={categoryId}
              tagId={tagId}
            />
          </div>
        </div>
      </section>
    </div>
  );
}
