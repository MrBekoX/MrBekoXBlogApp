'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

interface UseCacheSyncedDataOptions<T> {
  /** Initial data from server (SSR) */
  initialData: T | null;
  /** Current cache version from store */
  cacheVersion: number;
  /** Function to fetch fresh data */
  fetchFn: () => Promise<T | null>;
  /** Enable debug logging */
  debug?: boolean;
}

interface UseCacheSyncedDataResult<T> {
  /** Current data (initial or refreshed) */
  data: T | null;
  /** Whether data is being fetched */
  isLoading: boolean;
  /** Manual refresh function */
  refresh: () => Promise<void>;
}

/**
 * Hook for syncing server-side data with client-side cache invalidation.
 *
 * - Uses initialData on first render (SSR)
 * - Watches cacheVersion from store
 * - When cacheVersion changes, fetches fresh data
 * - Returns the most recent data (initial or refreshed)
 *
 * @example
 * ```tsx
 * const cacheVersion = usePostsStore((state) => state.cacheVersion);
 * const { data, isLoading } = useCacheSyncedData({
 *   initialData: serverPosts,
 *   cacheVersion,
 *   fetchFn: () => postsApi.getAll({ pageSize: 6 }),
 * });
 * ```
 */
export function useCacheSyncedData<T>({
  initialData,
  cacheVersion,
  fetchFn,
  debug = false,
}: UseCacheSyncedDataOptions<T>): UseCacheSyncedDataResult<T> {
  // Track the previous cache version to detect changes
  const prevCacheVersionRef = useRef(cacheVersion);
  const isInitialMountRef = useRef(true);

  // Store fetchFn in a ref to avoid unnecessary effect triggers
  const fetchFnRef = useRef(fetchFn);
  fetchFnRef.current = fetchFn;

  // State for refreshed data and loading
  const [refreshedData, setRefreshedData] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const log = useCallback((..._args: unknown[]) => {
    // logging disabled
  }, []);

  // Refresh function that can be called manually or on cache invalidation
  const refresh = useCallback(async () => {
    log('Fetching fresh data...');
    setIsLoading(true);

    try {
      const freshData = await fetchFnRef.current();
      if (freshData !== null) {
        log('Fresh data received');
        setRefreshedData(freshData);
      }
    } catch {
      // fetch error silenced
    } finally {
      setIsLoading(false);
    }
  }, [log]);

  // Watch for cacheVersion changes
  useEffect(() => {
    // First mount handling
    if (isInitialMountRef.current) {
      isInitialMountRef.current = false;
      prevCacheVersionRef.current = cacheVersion;

      // If cacheVersion > 0, an invalidation happened before this component mounted
      // This can happen due to React StrictMode remounts or navigation
      // We should fetch fresh data to ensure consistency
      if (cacheVersion > 0) {
        log(`Initial mount but cacheVersion is ${cacheVersion}, fetching fresh data`);
        refresh();
        return;
      }

      log('Initial mount, using server data');
      return;
    }

    // Check if cacheVersion changed after initial mount
    if (prevCacheVersionRef.current !== cacheVersion) {
      log(`Cache version changed: ${prevCacheVersionRef.current} -> ${cacheVersion}`);
      prevCacheVersionRef.current = cacheVersion;
      refresh();
    }
  }, [cacheVersion, refresh, log]);

  // Return refreshed data if available, otherwise initial data
  const data = refreshedData ?? initialData;

  return {
    data,
    isLoading,
    refresh,
  };
}
