import { create } from 'zustand';
import type { BlogPost, CreatePostRequest, PaginatedResult, UpdatePostRequest } from '@/types';
import { postsApi, getErrorMessage } from '@/lib/api';

// Cache configuration
const CACHE_DURATION = 5 * 60 * 1000; // 5 minutes in milliseconds

interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

interface PostsCache {
  [key: string]: CacheEntry<PaginatedResult<BlogPost>>;
}

interface PostsState {
  posts: PaginatedResult<BlogPost> | null;
  currentPost: BlogPost | null;
  isLoading: boolean;
  error: string | null;
  cache: PostsCache;
  postCache: { [slug: string]: CacheEntry<BlogPost> };
  // Cache version - incremented on invalidation to trigger refetch in components
  cacheVersion: number;

  fetchPosts: (params?: {
    pageNumber?: number;
    pageSize?: number;
    status?: string;
    categoryId?: string;
    tagId?: string;
    search?: string;
    sortBy?: string;
    sortDescending?: boolean;
  }, forceRefresh?: boolean) => Promise<void>;
  fetchPostById: (id: string) => Promise<void>;
  fetchPostBySlug: (slug: string, forceRefresh?: boolean) => Promise<void>;
  createPost: (data: CreatePostRequest) => Promise<BlogPost | null>;
  updatePost: (id: string, data: UpdatePostRequest) => Promise<BlogPost | null>;
  deletePost: (id: string) => Promise<boolean>;
  publishPost: (id: string) => Promise<boolean>;
  unpublishPost: (id: string) => Promise<boolean>;
  archivePost: (id: string) => Promise<boolean>;
  clearCurrentPost: () => void;
  clearError: () => void;
  invalidateCache: () => void;
}

// Generate cache key from params
const getCacheKey = (params?: Record<string, unknown>): string => {
  if (!params) return 'default';
  // Sort keys to ensure consistent cache keys regardless of param order
  return JSON.stringify(params, Object.keys(params).sort());
};

// Check if cache entry is still valid
const isCacheValid = <T>(entry: CacheEntry<T> | undefined): boolean => {
  if (!entry) return false;
  return Date.now() - entry.timestamp < CACHE_DURATION;
};

export const usePostsStore = create<PostsState>()((set, get) => ({
  posts: null,
  currentPost: null,
  isLoading: false,
  error: null,
  cache: {},
  postCache: {},
  cacheVersion: 0,

  fetchPosts: async (params, forceRefresh = false) => {
    const cacheKey = getCacheKey(params);
    const cachedEntry = get().cache[cacheKey];

    // Return cached data if valid and not forcing refresh
    if (!forceRefresh && isCacheValid(cachedEntry)) {
      set({ posts: cachedEntry.data, isLoading: false, error: null });
      return;
    }

    set({ isLoading: true, error: null });
    try {
      // API call is handled by postsApi which now includes the timestamp logic internally
      // or we pass extra params if needed. But since we updated api.ts, standard call is fine.
      const response = await postsApi.getAll(params);
      
      if (response.success && response.data) {
        const newCache = {
          ...get().cache,
          [cacheKey]: { data: response.data, timestamp: Date.now() }
        };
        set({ posts: response.data, isLoading: false, cache: newCache });
      } else {
        set({ error: response.message || 'Failed to fetch posts', isLoading: false });
      }
    } catch (error) {
      const message = getErrorMessage(error, 'Yazılar yüklenemedi');
      set({ error: message, isLoading: false });
    }
  },

  fetchPostById: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.getById(id);
      if (response.success && response.data) {
        set({ currentPost: response.data, isLoading: false });
      } else {
        set({ error: response.message || 'Failed to fetch post', isLoading: false });
      }
    } catch (error) {
      const message = getErrorMessage(error, 'Yazı yüklenemedi');
      set({ error: message, isLoading: false });
    }
  },

  fetchPostBySlug: async (slug: string, forceRefresh = false) => {
    const cachedPost = get().postCache[slug];

    // Return cached data if valid and not forcing refresh
    if (!forceRefresh && isCacheValid(cachedPost)) {
      set({ currentPost: cachedPost.data, isLoading: false, error: null });
      return;
    }

    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.getBySlug(slug);
      if (response.success && response.data) {
        const newPostCache = {
          ...get().postCache,
          [slug]: { data: response.data, timestamp: Date.now() }
        };
        set({ currentPost: response.data, isLoading: false, postCache: newPostCache });
      } else {
        set({ error: response.message || 'Failed to fetch post', isLoading: false });
      }
    } catch (error) {
      const message = getErrorMessage(error, 'Yazı yüklenemedi');
      set({ error: message, isLoading: false });
    }
  },

  createPost: async (data: CreatePostRequest) => {
    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.create(data);
      if (response.success && response.data) {
        // Invalidate cache immediately
        get().invalidateCache();
        set({ isLoading: false });
        // Fetch fresh data
        await get().fetchPosts(undefined, true);
        return response.data;
      } else {
        set({ error: response.message || 'Failed to create post', isLoading: false });
        return null;
      }
    } catch (error) {
      const message = getErrorMessage(error, 'Yazı oluşturulamadı');
      set({ error: message, isLoading: false });
      return null;
    }
  },

  updatePost: async (id: string, data: UpdatePostRequest) => {
    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.update(id, data);
      if (response.success && response.data) {
        get().invalidateCache();
        set({ currentPost: response.data, isLoading: false });
        // Ensure lists are refreshed
        await get().fetchPosts(undefined, true);
        return response.data;
      } else {
        set({ error: response.message || 'Failed to update post', isLoading: false });
        return null;
      }
    } catch (error) {
      const message = getErrorMessage(error, 'Yazı güncellenemedi');
      set({ error: message, isLoading: false });
      return null;
    }
  },

  deletePost: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.delete(id);
      if (response.success) {
        get().invalidateCache();
        set({ isLoading: false });
        await get().fetchPosts(undefined, true);
        return true;
      } else {
        set({ error: response.message || 'Failed to delete post', isLoading: false });
        return false;
      }
    } catch (error) {
      const message = getErrorMessage(error, 'Yazı silinemedi');
      set({ error: message, isLoading: false });
      return false;
    }
  },

  publishPost: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.publish(id);
      if (response.success && response.data) {
        // Critical: Invalidate cache and force refresh
        get().invalidateCache();
        set({ currentPost: response.data, isLoading: false });
        // Force refresh all lists immediately
        await get().fetchPosts(undefined, true);
        
        // Also refresh Next.js server cache for SSR pages
        try {
          const { revalidateCacheTag } = await import('@/app/actions/revalidate');
          await revalidateCacheTag('posts');
          // Trigger re-fetch instead of hard reload
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('posts-updated'));
          }
        } catch {
          // revalidate error silenced
        }
        
        return true;
      } else {
        set({ error: response.message || 'Failed to publish post', isLoading: false });
        return false;
      }
    } catch (error) {
      const message = getErrorMessage(error, 'Yazı yayınlanamadı');
      set({ error: message, isLoading: false });
      return false;
    }
  },

  archivePost: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.archive(id);
      if (response.success && response.data) {
        get().invalidateCache();
        set({ currentPost: response.data, isLoading: false });
        await get().fetchPosts(undefined, true);
        return true;
      } else {
        set({ error: response.message || 'Failed to archive post', isLoading: false });
        return false;
      }
    } catch (error) {
      const message = getErrorMessage(error, 'Yazı arşivlenemedi');
      set({ error: message, isLoading: false });
      return false;
    }
  },

  // Missing unpublish method added for completeness based on context
  unpublishPost: async (id: string) => {
      set({ isLoading: true, error: null });
      try {
        const response = await postsApi.unpublish(id);
        if (response.success && response.data) {
          get().invalidateCache();
          set({ currentPost: response.data, isLoading: false });
          await get().fetchPosts(undefined, true);
          return true;
        } else {
          set({ error: response.message || 'Failed to unpublish post', isLoading: false });
          return false;
        }
      } catch (error) {
        const message = getErrorMessage(error, 'Yazı yayından kaldırılamadı');
        set({ error: message, isLoading: false });
        return false;
      }
    },

  clearCurrentPost: () => set({ currentPost: null }),
  clearError: () => set({ error: null }),
  invalidateCache: () => {
    // Clear internal store cache
    set((state) => ({
      cache: {},
      postCache: {},
      // posts: null, // Removed to prevent UI flicker/empty state while fetching
      // currentPost: null, // Keep current post visible
      cacheVersion: state.cacheVersion + 1
    }));
  },
}));