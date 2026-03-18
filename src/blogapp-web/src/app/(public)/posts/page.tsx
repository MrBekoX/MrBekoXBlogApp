import { Metadata } from 'next';
import { fetchPosts } from '@/lib/server-api';
import { PostsListClient } from '@/components/posts/posts-list-client';

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

  const initialPosts = await fetchPosts({
    pageNumber: page,
    pageSize: 9,
    status: 'Published',
    search: search || undefined,
    categoryId: categoryId,
    tagId: tagId,
  });

  return (
    <div className="font-mono">
      {/* File header */}
      <div className="mb-6 border-b border-ide-border/50 pb-4">
        <h1
          className="text-2xl text-white glow-text uppercase tracking-tight mb-1"
          style={{ fontFamily: "'VT323', monospace" }}
        >
          <span className="text-ide-primary">ls</span> -la ./posts/
        </h1>
        <p className="text-xs text-gray-500">
          Yazılım geliştirme, teknoloji trendleri ve kişisel deneyimlerime dair makaleler
        </p>
      </div>

      {/* Posts list client component */}
      <PostsListClient
        initialPosts={initialPosts}
        initialSearch={search}
        initialPage={page}
        categoryId={categoryId}
        tagId={tagId}
      />
    </div>
  );
}
