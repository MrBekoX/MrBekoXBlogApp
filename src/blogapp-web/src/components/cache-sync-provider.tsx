'use client';

import { useCacheSync, CacheInvalidationEvent } from '@/hooks/use-cache-sync';
import { usePostsStore } from '@/stores/posts-store';
import { useCategoriesStore } from '@/stores/categories-store';
import { useTagsStore } from '@/stores/tags-store';

interface CacheSyncProviderProps {
  children: React.ReactNode;
  /** Enable debug logging */
  debug?: boolean;
}

/**
 * Provider component that automatically syncs frontend cache with backend.
 * Listens for cache invalidation events via SignalR and updates local stores.
 *
 * Client components using useCacheSyncedData hook will automatically refetch
 * when store's cacheVersion changes.
 */
export function CacheSyncProvider({ children, debug = false }: CacheSyncProviderProps) {
  const invalidatePostsCache = usePostsStore((state) => state.invalidateCache);
  const invalidateCategoriesCache = useCategoriesStore((state) => state.invalidateCache);
  const invalidateTagsCache = useTagsStore((state) => state.invalidateCache);

  const handleCacheInvalidation = (event: CacheInvalidationEvent) => {
    const target = event.target.toLowerCase();

    if (target.includes('posts') || target.includes('post')) {
      invalidatePostsCache();
    }

    if (target.includes('categories') || target.includes('category')) {
      invalidateCategoriesCache();
    }

    if (target.includes('tags') || target.includes('tag')) {
      invalidateTagsCache();
    }
  };

  useCacheSync({
    onInvalidate: handleCacheInvalidation,
    groups: ['posts_list', 'categories_list', 'tags_list'], // Subscribe to backend cache groups
    debug,
  });

  return <>{children}</>;
}

/**
 * Hook to manually trigger cache sync connection.
 * Use this if you need to control when cache sync starts.
 */
export function useCacheSyncConnection(debug = false) {
  const invalidatePostsCache = usePostsStore((state) => state.invalidateCache);
  const invalidateCategoriesCache = useCategoriesStore((state) => state.invalidateCache);
  const invalidateTagsCache = useTagsStore((state) => state.invalidateCache);

  return useCacheSync({
    onInvalidate: (event) => {
      const target = event.target.toLowerCase();
      if (target.includes('posts') || target.includes('post')) {
        invalidatePostsCache();
      }
      if (target.includes('categories') || target.includes('category')) {
        invalidateCategoriesCache();
      }
      if (target.includes('tags') || target.includes('tag')) {
        invalidateTagsCache();
      }
    },
    groups: ['posts_list', 'categories_list', 'tags_list'],
    debug,
  });
}
