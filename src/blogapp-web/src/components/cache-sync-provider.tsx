'use client';

import { useEffect } from 'react';
import { useCacheSync, CacheInvalidationEvent } from '@/hooks/use-cache-sync';
import { usePostsStore } from '@/stores/posts-store';

interface CacheSyncProviderProps {
  children: React.ReactNode;
  /** Enable debug logging */
  debug?: boolean;
}

/**
 * Provider component that automatically syncs frontend cache with backend.
 * Listens for cache invalidation events via SignalR and updates local stores.
 */
export function CacheSyncProvider({ children, debug = false }: CacheSyncProviderProps) {
  const invalidatePostsCache = usePostsStore((state) => state.invalidateCache);

  const handleCacheInvalidation = (event: CacheInvalidationEvent) => {
    if (debug) {
      console.log('[CacheSyncProvider] Received invalidation:', event);
    }

    // Determine which store to invalidate based on the event target
    const target = event.target.toLowerCase();

    if (target.includes('posts') || target.includes('post')) {
      if (debug) {
        console.log('[CacheSyncProvider] Invalidating posts cache');
      }
      invalidatePostsCache();
    }

    // Add more store invalidations here as needed:
    // if (target.includes('categories') || target.includes('category')) {
    //   invalidateCategoriesCache();
    // }
    // if (target.includes('tags') || target.includes('tag')) {
    //   invalidateTagsCache();
    // }
  };

  useCacheSync({
    onInvalidate: handleCacheInvalidation,
    groups: ['posts'], // Subscribe to posts group for targeted notifications
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

  return useCacheSync({
    onInvalidate: (event) => {
      const target = event.target.toLowerCase();
      if (target.includes('posts') || target.includes('post')) {
        invalidatePostsCache();
      }
    },
    debug,
  });
}
