'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { usePostsStore } from '@/stores/posts-store';
import type { BlogPost, PaginatedResult } from '@/types';
import { PostCard } from '@/components/posts/post-card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Search, ChevronLeft, ChevronRight, BookOpen, Loader2 } from 'lucide-react';

// Debounce hook
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
}

// Minimum arama uzunluğu
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
  const router = useRouter();
  const searchParams = useSearchParams();
  // Get fetchPosts with useCallback to prevent infinite loop in useEffect dependency
  const fetchPostsFromStore = usePostsStore((state) => state.fetchPosts);
  const posts = usePostsStore((state) => state.posts);
  const isLoading = usePostsStore((state) => state.isLoading);
  const [search, setSearch] = useState(initialSearch);
  const [isSearching, setIsSearching] = useState(false);
  const [currentPage, setCurrentPage] = useState(initialPage);
  
  // Use server data initially, then client data after interaction
  const [hasInteracted, setHasInteracted] = useState(false);
  const displayPosts = hasInteracted && posts ? posts : initialPosts;
  
  // Debounced search term
  const debouncedSearch = useDebounce(search, DEBOUNCE_DELAY);
  
  // Track if this is initial load or search
  const isInitialLoad = useRef(true);
  
  // AbortController for cancelling previous requests (race condition fix)
  const abortControllerRef = useRef<AbortController | null>(null);

  // Fetch posts when search/page changes (after initial load)
  useEffect(() => {
    if (isInitialLoad.current) {
      isInitialLoad.current = false;
      return;
    }

    const performSearch = async () => {
      const searchTerm = debouncedSearch.trim();
      const shouldSearch = searchTerm.length === 0 || searchTerm.length >= MIN_SEARCH_LENGTH;
      
      if (!shouldSearch) return;

      // Cancel previous request if still pending
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      
      // Create new AbortController for this request
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
        // Ignore abort errors
        if (error instanceof Error && error.name === 'AbortError') {
          return;
        }
        // Search failed silently - user can retry
      } finally {
        setIsSearching(false);
      }
    };

    performSearch();
    
    // Cleanup: abort on unmount
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  // Note: fetchPostsFromStore is stable (from Zustand selector) so no infinite loop
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
      });
    }
  };
  
  const getSearchHelperText = () => {
    const trimmed = search.trim();
    if (trimmed.length > 0 && trimmed.length < MIN_SEARCH_LENGTH) {
      return `En az ${MIN_SEARCH_LENGTH} karakter girin`;
    }
    return null;
  };

  const showLoading = isLoading || isSearching;
  const postsData = displayPosts;

  return (
    <>
      {/* Search Form */}
      <form onSubmit={handleSearch} className="flex max-w-lg mx-auto gap-3 pt-4">
        <div className="relative flex-1">
          {isSearching ? (
            <Loader2 className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-primary animate-spin" />
          ) : (
            <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          )}
          <Input
            placeholder="Yazılarda ara..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-11 h-12 bg-background/80 border-border/50 focus:border-primary"
          />
        </div>
        <Button type="submit" size="lg" className="px-6" disabled={isSearching}>
          {isSearching ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Ara'}
        </Button>
      </form>
      
      {/* Helper text */}
      {getSearchHelperText() && (
        <p className="text-sm text-muted-foreground mt-2 animate-fade-in text-center">
          {getSearchHelperText()}
        </p>
      )}

      {/* Posts Grid */}
      <section className="container py-12 md:py-16">
        <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-3">
          {showLoading ? (
            Array.from({ length: 9 }).map((_, i) => (
              <div key={i} className="space-y-4 animate-fade-in" style={{ animationDelay: `${i * 0.05}s` }}>
                <Skeleton className="aspect-video w-full rounded-xl" />
                <Skeleton className="h-6 w-3/4" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            ))
          ) : postsData?.items?.length ? (
            postsData.items.map((post, index) => (
              <div 
                key={post.id} 
                className="animate-fade-in-up" 
                style={{ animationDelay: `${index * 0.05}s` }}
              >
                <PostCard post={post} />
              </div>
            ))
          ) : (
            <div className="col-span-full py-20 text-center animate-fade-in">
              <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-muted flex items-center justify-center">
                <BookOpen className="w-10 h-10 text-muted-foreground" />
              </div>
              <h3 className="text-xl font-semibold mb-2">
                {search.trim() ? 'Böyle bir makale bulunamadı' : 'Henüz yazı yok'}
              </h3>
              <p className="text-muted-foreground max-w-md mx-auto">
                {search.trim() 
                  ? `"${search.trim()}" aramasıyla eşleşen makale bulunamadı.` 
                  : 'Yakında yeni içerikler eklenecek!'}
              </p>
              {search.trim() && (
                <Button 
                  variant="outline" 
                  className="mt-6"
                  onClick={() => {
                    setSearch('');
                    setCurrentPage(1);
                  }}
                >
                  Aramayı Temizle
                </Button>
              )}
            </div>
          )}
        </div>

        {/* Pagination */}
        {postsData && postsData.totalPages > 1 && (
          <div className="mt-12 flex items-center justify-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={!postsData.hasPreviousPage}
              onClick={() => {
                setHasInteracted(true);
                setCurrentPage((p) => p - 1);
              }}
              className="gap-1"
            >
              <ChevronLeft className="h-4 w-4" />
              Önceki
            </Button>

            <div className="flex items-center gap-1 mx-4">
              {Array.from({ length: postsData.totalPages }, (_, i) => i + 1)
                .filter((page) => {
                  const distance = Math.abs(page - currentPage);
                  return distance === 0 || distance === 1 || page === 1 || page === postsData.totalPages;
                })
                .map((page, index, array) => (
                  <div key={page} className="flex items-center">
                    {index > 0 && array[index - 1] !== page - 1 && (
                      <span className="px-2 text-muted-foreground">...</span>
                    )}
                    <Button
                      variant={currentPage === page ? 'default' : 'ghost'}
                      size="sm"
                      onClick={() => {
                        setHasInteracted(true);
                        setCurrentPage(page);
                      }}
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
              disabled={!postsData.hasNextPage}
              onClick={() => {
                setHasInteracted(true);
                setCurrentPage((p) => p + 1);
              }}
              className="gap-1"
            >
              Sonraki
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        )}
      </section>
    </>
  );
}
