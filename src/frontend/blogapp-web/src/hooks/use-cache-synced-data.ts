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
 * @sample
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
}: UseCacheSyncedDataOptions<T>): UseCacheSyncedDataResult<T> {
  // An inline fetch callback must not restart an in-flight invalidation fetch.
  // Publish the latest callback at commit time, not by mutating a render ref.
  const fetchFnRef = useRef(fetchFn);
  useEffect(() => { fetchFnRef.current = fetchFn; }, [fetchFn]);
  const requestSequenceRef = useRef(0);
  const [snapshot, setSnapshot] = useState<{ data: T | null; version: number | null }>(() => ({
    data: null, version: cacheVersion > 0 ? null : cacheVersion,
  }));
  const [manualRequests, setManualRequests] = useState(0);

  const readVersion = useCallback(async (version: number, isCurrent: () => boolean) => {
    const requestSequence = ++requestSequenceRef.current;
    let freshData: T | null = null;
    try {
      freshData = await fetchFnRef.current();
    } catch {
      // A failed or empty refresh retains the last usable data.
    } finally {
      if (isCurrent() && requestSequence === requestSequenceRef.current) {
        setSnapshot((previous) => ({ data: freshData ?? previous.data, version }));
      }
    }
  }, []);

  // Automatic loading is derived from the external cache version. No state is
  // synchronously reset by this effect; only the async result settles it.
  useEffect(() => {
    if (snapshot.version === cacheVersion) return;
    let cancelled = false;
    void readVersion(cacheVersion, () => !cancelled);
    return () => { cancelled = true; };
  }, [cacheVersion, snapshot.version, readVersion]);

  const refresh = useCallback(async () => {
    setManualRequests((pending) => pending + 1);
    try {
      await readVersion(cacheVersion, () => true);
    } finally {
      // Every manual promise settles independently of whether its data was
      // superseded by an automatic invalidation request.
      setManualRequests((pending) => pending - 1);
    }
  }, [cacheVersion, readVersion]);

  return {
    data: snapshot.data ?? initialData,
    isLoading: manualRequests > 0 || snapshot.version !== cacheVersion,
    refresh,
  };
}
