'use client';

import { useCallback, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useCacheSync, CacheInvalidationEvent } from '@/hooks/use-cache-sync';
import { usePostsStore } from '@/stores/posts-store';
import { useCategoriesStore } from '@/stores/categories-store';
import { useTagsStore } from '@/stores/tags-store';
import { revalidateCacheTag } from '@/app/actions/revalidate';

interface CacheSyncProviderProps {
  children: React.ReactNode;
  /** Enable debug logging */
  debug?: boolean;
}

type CacheTag = 'posts' | 'categories' | 'tags';

const INVALIDATION_DEBOUNCE_MS = 150;

function getAffectedTags(event: CacheInvalidationEvent): CacheTag[] {
  const target = event.target.toLowerCase();
  const tags = new Set<CacheTag>();

  if (target.includes('posts') || target.includes('post')) tags.add('posts');
  if (target.includes('categories') || target.includes('category')) tags.add('categories');
  if (target.includes('tags') || target.includes('tag')) tags.add('tags');

  return Array.from(tags);
}

/**
 * Provider component that automatically syncs frontend cache with backend.
 * Listens for cache invalidation events via SignalR and updates local stores.
 *
 * Client components using useCacheSyncedData hook will automatically refetch
 * when store's cacheVersion changes.
 */
export function CacheSyncProvider({ children, debug = false }: CacheSyncProviderProps) {
  const router = useRouter();
  const invalidatePostsCache = usePostsStore((state) => state.invalidateCache);
  const invalidateCategoriesCache = useCategoriesStore((state) => state.invalidateCache);
  const invalidateTagsCache = useTagsStore((state) => state.invalidateCache);

  const pendingTagsRef = useRef<Set<CacheTag>>(new Set());
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const needsRefreshOnVisibleRef = useRef(false);

  const invalidateLocalStores = useCallback((tags: Iterable<CacheTag>) => {
    const uniqueTags = new Set(tags);

    if (uniqueTags.has('posts')) invalidatePostsCache();
    if (uniqueTags.has('categories')) invalidateCategoriesCache();
    if (uniqueTags.has('tags')) invalidateTagsCache();
  }, [invalidatePostsCache, invalidateCategoriesCache, invalidateTagsCache]);

  const flushPendingInvalidations = useCallback(async () => {
    const tags = Array.from(pendingTagsRef.current);
    pendingTagsRef.current.clear();

    if (tags.length === 0) return;

    await Promise.all(tags.map((tag) => revalidateCacheTag(tag)));

    if (document.hidden) {
      // Browser throttles router.refresh() in background tabs.
      // Defer the refresh until the tab becomes visible again.
      needsRefreshOnVisibleRef.current = true;
    } else {
      router.refresh();
    }
  }, [router]);

  const scheduleFlush = useCallback(() => {
    if (flushTimerRef.current) return;

    flushTimerRef.current = setTimeout(() => {
      flushTimerRef.current = null;
      void flushPendingInvalidations();
    }, INVALIDATION_DEBOUNCE_MS);
  }, [flushPendingInvalidations]);

  const queueInvalidation = useCallback((tags: CacheTag[]) => {
    if (tags.length === 0) return;

    for (const tag of tags) {
      pendingTagsRef.current.add(tag);
    }

    // Keep client-state views fresh immediately.
    invalidateLocalStores(tags);
    // Revalidate server-side caches once per invalidation burst.
    scheduleFlush();
  }, [invalidateLocalStores, scheduleFlush]);

  const handleCacheInvalidation = (event: CacheInvalidationEvent) => {
    queueInvalidation(getAffectedTags(event));
  };

  const handleReconnected = () => {
    // Connection was restored after a drop; catch up in one pass.
    queueInvalidation(['posts', 'categories', 'tags']);
  };

  useEffect(() => {
    const onVisibilityChange = () => {
      if (!document.hidden && needsRefreshOnVisibleRef.current) {
        needsRefreshOnVisibleRef.current = false;
        router.refresh();
      }
    };

    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      if (flushTimerRef.current) {
        clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
    };
  }, [router]);

  useCacheSync({
    onInvalidate: handleCacheInvalidation,
    onReconnected: handleReconnected,
    groups: ['posts', 'categories', 'tags'],
    debug,
  });

  return <>{children}</>;
}

/**
 * Hook to manually trigger cache sync connection.
 * Use this if you need to control when cache sync starts.
 */
export function useCacheSyncConnection(debug = false) {
  const router = useRouter();
  const invalidatePostsCache = usePostsStore((state) => state.invalidateCache);
  const invalidateCategoriesCache = useCategoriesStore((state) => state.invalidateCache);
  const invalidateTagsCache = useTagsStore((state) => state.invalidateCache);

  return useCacheSync({
    onInvalidate: async (event) => {
      const tags = getAffectedTags(event);

      if (tags.includes('posts')) invalidatePostsCache();
      if (tags.includes('categories')) invalidateCategoriesCache();
      if (tags.includes('tags')) invalidateTagsCache();

      if (tags.length > 0) {
        await Promise.all(tags.map((tag) => revalidateCacheTag(tag)));
        router.refresh();
      }
    },
    onReconnected: async () => {
      invalidatePostsCache();
      invalidateCategoriesCache();
      invalidateTagsCache();
      await Promise.all([
        revalidateCacheTag('posts'),
        revalidateCacheTag('categories'),
        revalidateCacheTag('tags'),
      ]);
      router.refresh();
    },
    groups: ['posts', 'categories', 'tags'],
    debug,
  });
}
