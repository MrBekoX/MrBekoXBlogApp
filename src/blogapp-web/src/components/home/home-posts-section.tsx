'use client';

import Link from 'next/link';
import { usePostsStore } from '@/stores/posts-store';
import { useCacheSyncedData } from '@/hooks/use-cache-synced-data';
import { postsApi } from '@/lib/api';
import { PostCard } from '@/components/posts/post-card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ArrowRight, BookOpen } from 'lucide-react';
import type { BlogPost } from '@/types';

interface HomePostsSectionProps {
  initialPosts: BlogPost[];
}

/**
 * Client component for home page posts section.
 * Uses server data initially, then syncs with cache invalidation events.
 */
export function HomePostsSection({ initialPosts }: HomePostsSectionProps) {
  const cacheVersion = usePostsStore((state) => state.cacheVersion);

  const { data: posts, isLoading } = useCacheSyncedData({
    initialData: initialPosts,
    cacheVersion,
    fetchFn: async () => {
      const response = await postsApi.getAll({
        pageSize: 6,
        status: 'Published',
        sortBy: 'publishedat',
        sortDescending: true,
      });
      return response.success ? (response.data?.items ?? []) : null;
    },
    debug: process.env.NODE_ENV === 'development',
  });

  const displayPosts = posts ?? [];

  return (
    <section className="border-t">
      <div className="container py-20 md:py-28">
        {/* Section Header */}
        <div className="text-center space-y-4 mb-12">
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight">
            Son Yazılar
          </h2>
          <p className="text-muted-foreground text-lg max-w-2xl mx-auto">
            En son paylaştığım yazılar ve düşünceler
          </p>
        </div>

        {/* Posts Grid */}
        <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-3 max-w-6xl mx-auto">
          {isLoading ? (
            // Loading skeletons
            Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="space-y-4 animate-fade-in" style={{ animationDelay: `${i * 0.1}s` }}>
                <Skeleton className="aspect-video w-full rounded-xl" />
                <Skeleton className="h-6 w-3/4" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            ))
          ) : displayPosts.length > 0 ? (
            displayPosts.map((post, index) => (
              <div
                key={post.id}
                className="animate-fade-in-up"
                style={{ animationDelay: `${index * 0.1}s` }}
              >
                <PostCard post={post} />
              </div>
            ))
          ) : (
            <div className="col-span-full text-center py-16">
              <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-muted flex items-center justify-center">
                <BookOpen className="w-10 h-10 text-muted-foreground" />
              </div>
              <p className="text-xl text-muted-foreground mb-4">
                Henüz yazı yok
              </p>
              <p className="text-muted-foreground mb-6">
                Yakında yeni içerikler eklenecek!
              </p>
            </div>
          )}
        </div>

        {/* View All Button */}
        {displayPosts.length > 0 && (
          <div className="text-center mt-12">
            <Button asChild variant="outline" size="lg" className="group">
              <Link href="/posts">
                Tüm Yazılar
                <ArrowRight className="ml-2 h-4 w-4 transition-transform group-hover:translate-x-1" />
              </Link>
            </Button>
          </div>
        )}
      </div>
    </section>
  );
}
