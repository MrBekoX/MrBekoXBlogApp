'use client';

import { useEffect, useState, useRef } from 'react';
import { usePostsStore } from '@/stores/posts-store';
import type { BlogPost, PaginatedResult } from '@/types';
import { PostCard } from '@/components/posts/post-card';
import { Skeleton } from '@/components/ui/skeleton';
import { Search, ChevronLeft, ChevronRight, FileX, Loader2 } from 'lucide-react';

// Debounce hook
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);
  useEffect(() => {
    const handler = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(handler);
  }, [value, delay]);
  return debouncedValue;
}

const MIN_SEARCH_LENGTH = 2;
const DEBOUNCE_DELAY = 400;

interface PostsListClientProps {
  initialPosts: PaginatedResult<BlogPost> | null;
  initialSearch?: string;
  initialPage?: number;
  categoryId?: string;
  tagId?: string;
}

export function PostsListClient({
  initialPosts,
  initialSearch = '',
  initialPage = 1,
  categoryId,
  tagId,
}: PostsListClientProps) {
  const fetchPostsFromStore = usePostsStore((state) => state.fetchPosts);
  const posts = usePostsStore((state) => state.posts);
  const isLoading = usePostsStore((state) => state.isLoading);
  const cacheVersion = usePostsStore((state) => state.cacheVersion);
  const [search, setSearch] = useState(initialSearch);
  const [isSearching, setIsSearching] = useState(false);
  const [currentPage, setCurrentPage] = useState(initialPage);
  const [hasInteracted, setHasInteracted] = useState(false);
  const displayPosts = hasInteracted && posts ? posts : initialPosts;
  const debouncedSearch = useDebounce(search, DEBOUNCE_DELAY);
  const isInitialLoad = useRef(true);
  const prevCacheVersion = useRef(cacheVersion);
  const abortControllerRef = useRef<AbortController | null>(null);

  // React to SignalR cache invalidation: re-fetch when cacheVersion changes
  useEffect(() => {
    if (prevCacheVersion.current === cacheVersion) return;
    prevCacheVersion.current = cacheVersion;

    // If user hasn't interacted, server component re-render (via router.refresh) handles it
    if (!hasInteracted) return;

    // User has interacted — zustand store has stale data, force re-fetch
    fetchPostsFromStore({
      pageNumber: currentPage,
      pageSize: 9,
      status: 'Published',
      search: search.trim() || undefined,
      categoryId: categoryId || undefined,
      tagId: tagId || undefined,
    }, true).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cacheVersion]);

  useEffect(() => {
    if (isInitialLoad.current) {
      isInitialLoad.current = false;
      return;
    }
    const performSearch = async () => {
      const searchTerm = debouncedSearch.trim();
      if (searchTerm.length > 0 && searchTerm.length < MIN_SEARCH_LENGTH) return;
      if (abortControllerRef.current) abortControllerRef.current.abort();
      abortControllerRef.current = new AbortController();
      setIsSearching(true);
      setHasInteracted(true);
      try {
        await fetchPostsFromStore({
          pageNumber: currentPage,
          pageSize: 9,
          status: 'Published',
          search: searchTerm || undefined,
          categoryId: categoryId || undefined,
          tagId: tagId || undefined,
        }, true);
      } catch (error) {
        if (error instanceof Error && error.name === 'AbortError') return;
      } finally {
        setIsSearching(false);
      }
    };
    performSearch();
    return () => { abortControllerRef.current?.abort(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch, currentPage, categoryId, tagId]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const searchTerm = search.trim();
    if (searchTerm.length >= MIN_SEARCH_LENGTH || searchTerm.length === 0) {
      setCurrentPage(1);
      setHasInteracted(true);
      fetchPostsFromStore({
        pageNumber: 1,
        pageSize: 9,
        status: 'Published',
        search: searchTerm || undefined,
        categoryId: categoryId || undefined,
        tagId: tagId || undefined,
      }, true).catch(() => {});
    }
  };

  const helperText =
    search.trim().length > 0 && search.trim().length < MIN_SEARCH_LENGTH
      ? `en az ${MIN_SEARCH_LENGTH} karakter girin`
      : null;

  const showLoading = isLoading || isSearching;
  const postsData = displayPosts;
  const totalCount = postsData?.totalCount ?? 0;

  return (
    <div className="font-mono">
      {/* ── Terminal grep search ────────────────────────────── */}
      <form onSubmit={handleSearch} className="mb-6">
        <div className="flex items-center gap-2 border border-ide-border bg-ide-sidebar rounded px-3 py-2 focus-within:border-ide-primary/60 transition-colors">
          <span className="text-ide-primary text-sm shrink-0 font-bold">$</span>
          <span className="text-gray-600 text-xs shrink-0 hidden sm:inline">grep -r</span>
          <div className="relative flex-1">
            {isSearching ? (
              <Loader2 className="absolute left-0 top-1/2 -translate-y-1/2 w-3 h-3 text-ide-primary animate-spin" />
            ) : (
              <Search className="absolute left-0 top-1/2 -translate-y-1/2 w-3 h-3 text-gray-600" />
            )}
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="yazılarda ara..."
              className="w-full bg-transparent text-sm text-white placeholder:text-gray-600 outline-none pl-5"
              autoComplete="off"
              spellCheck={false}
            />
          </div>
          <span className="text-gray-600 text-xs shrink-0 hidden sm:inline">./posts/</span>
          <button
            type="submit"
            disabled={isSearching}
            className="text-[10px] text-ide-primary border border-ide-primary/40 hover:border-ide-primary hover:bg-ide-primary/10 px-2 py-0.5 rounded transition-colors disabled:opacity-40 shrink-0"
          >
            ENTER ↵
          </button>
        </div>

        {/* Helper / result count */}
        <div className="mt-1.5 pl-1 text-[10px] text-gray-600">
          {helperText ? (
            <span className="text-yellow-600">↳ {helperText}</span>
          ) : search.trim() && !showLoading && postsData ? (
            <span>
              ↳ <span className="text-ide-primary">{totalCount}</span> sonuç bulundu:{' '}
              <span className="text-gray-500">&quot;{search.trim()}&quot;</span>
            </span>
          ) : !search.trim() && postsData ? (
            <span>↳ toplam <span className="text-ide-primary">{totalCount}</span> yazı</span>
          ) : null}
        </div>
      </form>

      {/* ── File list ─────────────────────────────────────────── */}
      <div className="border border-ide-border rounded overflow-hidden">
        {/* Table header */}
        <div className="flex items-center gap-3 px-3 py-1.5 bg-ide-sidebar border-b border-ide-border text-[10px] text-gray-600 uppercase tracking-widest">
          <span className="w-4 shrink-0" />
          <span className="flex-1">dosya / başlık</span>
          <span className="hidden sm:block w-24 text-right">tarih</span>
          <span className="hidden md:block w-16 text-right">görüntülenme</span>
        </div>

        {showLoading ? (
          <div className="divide-y divide-ide-border/40">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex items-start gap-3 py-4 px-3">
                <Skeleton className="w-4 h-4 bg-ide-border shrink-0 mt-0.5" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-2.5 w-32 bg-ide-border" />
                  <Skeleton className="h-3.5 w-3/4 bg-ide-border" />
                  <Skeleton className="h-2.5 w-full bg-ide-border" />
                  <div className="flex gap-3">
                    <Skeleton className="h-2.5 w-16 bg-ide-border" />
                    <Skeleton className="h-2.5 w-12 bg-ide-border" />
                    <Skeleton className="h-2.5 w-10 bg-ide-border" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : postsData?.items?.length ? (
          <div>
            {postsData.items.map((post) => (
              <PostCard key={post.id} post={post} />
            ))}
          </div>
        ) : (
          /* Empty state */
          <div className="py-16 text-center space-y-3">
            <FileX className="w-8 h-8 mx-auto text-gray-700" />
            <div className="text-sm text-gray-500">
              {search.trim()
                ? <><span className="text-ide-primary">$</span> grep &quot;{search.trim()}&quot; — <span className="text-red-400">eşleşme bulunamadı</span></>
                : <><span className="text-ide-primary">$</span> ls ./posts/ — <span className="text-gray-600">henüz yazı yok</span></>
              }
            </div>
            {search.trim() && (
              <button
                onClick={() => { setSearch(''); setCurrentPage(1); }}
                className="text-[11px] text-gray-500 hover:text-ide-primary border border-ide-border/60 hover:border-ide-primary/40 px-3 py-1 rounded transition-colors"
              >
                aramayı temizle
              </button>
            )}
          </div>
        )}
      </div>

      {/* ── Pagination ─────────────────────────────────────────── */}
      {postsData && postsData.totalPages != null && postsData.totalPages > 1 && (
        <div className="mt-6 flex items-center justify-center gap-1 text-xs font-mono">
          <button
            disabled={!postsData.hasPreviousPage}
            onClick={() => { setHasInteracted(true); setCurrentPage((p) => p - 1); }}
            className="flex items-center gap-1 px-3 py-1.5 border border-ide-border text-gray-500 hover:border-ide-primary/50 hover:text-ide-primary transition-colors disabled:opacity-30 disabled:cursor-not-allowed rounded"
          >
            <ChevronLeft className="w-3 h-3" />
            önceki
          </button>

          <div className="flex items-center gap-1 mx-2">
            {Array.from({ length: postsData.totalPages }, (_, i) => i + 1)
              .filter((page) => {
                const d = Math.abs(page - currentPage);
                return d === 0 || d === 1 || page === 1 || page === postsData.totalPages;
              })
              .map((page, index, array) => (
                <span key={page} className="flex items-center">
                  {index > 0 && array[index - 1] !== page - 1 && (
                    <span className="px-1 text-gray-700">…</span>
                  )}
                  <button
                    onClick={() => { setHasInteracted(true); setCurrentPage(page); }}
                    className={`w-8 h-7 rounded transition-colors ${
                      currentPage === page
                        ? 'bg-ide-primary text-black font-bold'
                        : 'text-gray-500 hover:text-ide-primary border border-transparent hover:border-ide-border'
                    }`}
                  >
                    {page}
                  </button>
                </span>
              ))}
          </div>

          <button
            disabled={!postsData.hasNextPage}
            onClick={() => { setHasInteracted(true); setCurrentPage((p) => p + 1); }}
            className="flex items-center gap-1 px-3 py-1.5 border border-ide-border text-gray-500 hover:border-ide-primary/50 hover:text-ide-primary transition-colors disabled:opacity-30 disabled:cursor-not-allowed rounded"
          >
            sonraki
            <ChevronRight className="w-3 h-3" />
          </button>
        </div>
      )}
    </div>
  );
}
