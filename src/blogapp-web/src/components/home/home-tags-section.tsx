'use client';

import Link from 'next/link';
import { useTagsStore } from '@/stores/tags-store';
import { useCacheSyncedData } from '@/hooks/use-cache-synced-data';
import { tagsApi } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Hash } from 'lucide-react';
import type { Tag } from '@/types';

interface HomeTagsSectionProps {
  initialTags: Tag[];
}

/**
 * Client component for home page tags section.
 * Uses server data initially, then syncs with cache invalidation events.
 */
export function HomeTagsSection({ initialTags }: HomeTagsSectionProps) {
  const cacheVersion = useTagsStore((state) => state.cacheVersion);

  const { data: tags, isLoading } = useCacheSyncedData({
    initialData: initialTags,
    cacheVersion,
    fetchFn: async () => {
      const response = await tagsApi.getAll();
      return response.success ? (response.data ?? []) : null;
    },
    debug: process.env.NODE_ENV === 'development',
  });

  const displayTags = tags ?? [];

  // Don't render section if no tags
  if (!isLoading && displayTags.length === 0) {
    return null;
  }

  return (
    <section className="border-t bg-muted/30">
      <div className="container py-12 md:py-16">
        <div className="text-center space-y-4 mb-8">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 border border-primary/20 text-sm text-primary">
            <Hash className="w-4 h-4" />
            <span>Popüler Etiketler</span>
          </div>
          <h2 className="text-2xl md:text-3xl font-bold tracking-tight">
            Konulara Göre Keşfet
          </h2>
        </div>

        <div className="flex flex-wrap justify-center gap-3 max-w-4xl mx-auto">
          {isLoading ? (
            // Loading skeletons
            Array.from({ length: 8 }).map((_, i) => (
              <Skeleton
                key={i}
                className="h-10 w-24 rounded-full animate-fade-in"
                style={{ animationDelay: `${i * 0.05}s` }}
              />
            ))
          ) : (
            displayTags.slice(0, 15).map((tag, index) => (
              <Link
                key={tag.id}
                href={`/posts?tagId=${tag.id}`}
                className="animate-fade-in"
                style={{ animationDelay: `${index * 0.05}s` }}
              >
                <Badge
                  variant="outline"
                  className="px-4 py-2 text-sm font-medium cursor-pointer hover:bg-primary hover:text-primary-foreground hover:border-primary transition-all duration-200"
                >
                  #{tag.name}
                  {tag.postCount !== undefined && tag.postCount > 0 && (
                    <span className="ml-2 text-xs opacity-60">
                      {tag.postCount}
                    </span>
                  )}
                </Badge>
              </Link>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
