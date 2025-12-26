'use client';

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { usePostsStore } from '@/stores/posts-store';
import { PostCard } from '@/components/posts/post-card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Search, ChevronLeft, ChevronRight, BookOpen, Sparkles } from 'lucide-react';

function PostsContent() {
  const searchParams = useSearchParams();
  const { posts, isLoading, fetchPosts } = usePostsStore();
  const [search, setSearch] = useState('');
  const [currentPage, setCurrentPage] = useState(1);

  useEffect(() => {
    const page = searchParams.get('page');
    if (page) {
      setCurrentPage(parseInt(page));
    }
  }, [searchParams]);

  useEffect(() => {
    fetchPosts({
      pageNumber: currentPage,
      pageSize: 9,
      status: 'Published',
      search: search || undefined,
    });
  }, [currentPage, search, fetchPosts]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setCurrentPage(1);
    fetchPosts({
      pageNumber: 1,
      pageSize: 9,
      status: 'Published',
      search: search || undefined,
    });
  };

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
              Yazılar & Düşünceler
            </h1>
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
              Yazılım geliştirme, teknoloji trendleri ve kişisel deneyimlerim hakkında yazdığım makaleler
            </p>

            {/* Search Form */}
            <form onSubmit={handleSearch} className="flex max-w-lg mx-auto gap-3 pt-4">
              <div className="relative flex-1">
                <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Yazılarda ara..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-11 h-12 bg-background/80 border-border/50 focus:border-primary"
                />
              </div>
              <Button type="submit" size="lg" className="px-6">
                Ara
              </Button>
            </form>
          </div>
        </div>
      </section>

      {/* Posts Grid */}
      <section className="container py-12 md:py-16">
        <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-3">
          {isLoading ? (
            Array.from({ length: 9 }).map((_, i) => (
              <div key={i} className="space-y-4 animate-fade-in" style={{ animationDelay: `${i * 0.05}s` }}>
                <Skeleton className="aspect-video w-full rounded-xl" />
                <Skeleton className="h-6 w-3/4" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            ))
          ) : posts?.items?.length ? (
            posts.items.map((post, index) => (
              <div 
                key={post.id} 
                className="animate-fade-in-up" 
                style={{ animationDelay: `${index * 0.05}s` }}
              >
                <PostCard post={post} />
              </div>
            ))
          ) : (
            <div className="col-span-full py-20 text-center">
              <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-muted flex items-center justify-center">
                <BookOpen className="w-10 h-10 text-muted-foreground" />
              </div>
              <h3 className="text-xl font-semibold mb-2">
                {search ? 'Sonuç bulunamadı' : 'Henüz yazı yok'}
              </h3>
              <p className="text-muted-foreground">
                {search 
                  ? 'Aramanızla eşleşen yazı bulunamadı. Farklı anahtar kelimeler deneyin.' 
                  : 'Yakında yeni içerikler eklenecek!'}
              </p>
            </div>
          )}
        </div>

        {/* Pagination */}
        {posts && posts.totalPages > 1 && (
          <div className="mt-12 flex items-center justify-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={!posts.hasPreviousPage}
              onClick={() => setCurrentPage((p) => p - 1)}
              className="gap-1"
            >
              <ChevronLeft className="h-4 w-4" />
              Önceki
            </Button>

            <div className="flex items-center gap-1 mx-4">
              {Array.from({ length: posts.totalPages }, (_, i) => i + 1)
                .filter((page) => {
                  const distance = Math.abs(page - currentPage);
                  return distance === 0 || distance === 1 || page === 1 || page === posts.totalPages;
                })
                .map((page, index, array) => (
                  <div key={page} className="flex items-center">
                    {index > 0 && array[index - 1] !== page - 1 && (
                      <span className="px-2 text-muted-foreground">...</span>
                    )}
                    <Button
                      variant={currentPage === page ? 'default' : 'ghost'}
                      size="sm"
                      onClick={() => setCurrentPage(page)}
                      className="w-10"
                    >
                      {page}
                    </Button>
                  </div>
                ))}
            </div>

            <Button
              variant="outline"
              size="sm"
              disabled={!posts.hasNextPage}
              onClick={() => setCurrentPage((p) => p + 1)}
              className="gap-1"
            >
              Sonraki
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        )}
      </section>
    </div>
  );
}

function PostsLoading() {
  return (
    <div className="min-h-screen">
      <section className="border-b bg-gradient-to-br from-primary/5 via-background to-accent/5">
        <div className="container py-16 md:py-20">
          <div className="max-w-3xl mx-auto text-center space-y-6">
            <Skeleton className="h-8 w-32 mx-auto rounded-full" />
            <Skeleton className="h-12 w-80 mx-auto" />
            <Skeleton className="h-6 w-96 mx-auto" />
            <Skeleton className="h-12 w-full max-w-lg mx-auto" />
          </div>
        </div>
      </section>
      <section className="container py-12 md:py-16">
        <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 9 }).map((_, i) => (
            <div key={i} className="space-y-4">
              <Skeleton className="aspect-video w-full rounded-xl" />
              <Skeleton className="h-6 w-3/4" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export default function PostsPage() {
  return (
    <Suspense fallback={<PostsLoading />}>
      <PostsContent />
    </Suspense>
  );
}
