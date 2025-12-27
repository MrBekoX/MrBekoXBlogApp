import { create } from 'zustand';
import type { BlogPost, CreatePostRequest, PaginatedResult, UpdatePostRequest } from '@/types';
import { postsApi } from '@/lib/api';

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

  fetchPosts: (params?: {
    pageNumber?: number;
    pageSize?: number;
    status?: string;
    categoryId?: string;
    tagId?: string;
    search?: string;
  }, forceRefresh?: boolean) => Promise<void>;
  fetchPostById: (id: string) => Promise<void>;
  fetchPostBySlug: (slug: string, forceRefresh?: boolean) => Promise<void>;
  createPost: (data: CreatePostRequest) => Promise<BlogPost | null>;
  updatePost: (id: string, data: UpdatePostRequest) => Promise<BlogPost | null>;
  deletePost: (id: string) => Promise<boolean>;
  publishPost: (id: string) => Promise<boolean>;
  archivePost: (id: string) => Promise<boolean>;
  clearCurrentPost: () => void;
  clearError: () => void;
  invalidateCache: () => void;
}

// Generate cache key from params
const getCacheKey = (params?: Record<string, unknown>): string => {
  if (!params) return 'default';
  return JSON.stringify(params);
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
      const message = error instanceof Error ? error.message : 'Failed to fetch posts';
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
      const message = error instanceof Error ? error.message : 'Failed to fetch post';
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
      const message = error instanceof Error ? error.message : 'Failed to fetch post';
      set({ error: message, isLoading: false });
    }
  },

  createPost: async (data: CreatePostRequest) => {
    console.log('Creating post with data:', data);
    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.create(data);
      console.log('Create post response:', response);
      if (response.success && response.data) {
        // Invalidate cache after creating a new post
        get().invalidateCache();
        set({ isLoading: false });
        await get().fetchPosts(undefined, true);
        return response.data;
      } else {
        console.error('Create post failed:', response.message);
        set({ error: response.message || 'Failed to create post', isLoading: false });
        return null;
      }
    } catch (error) {
      console.error('Create post error:', error);
      const message = error instanceof Error ? error.message : 'Failed to create post';
      set({ error: message, isLoading: false });
      return null;
    }
  },

  updatePost: async (id: string, data: UpdatePostRequest) => {
    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.update(id, data);
      if (response.success && response.data) {
        // Invalidate cache after updating a post
        get().invalidateCache();
        set({ currentPost: response.data, isLoading: false });
        return response.data;
      } else {
        set({ error: response.message || 'Failed to update post', isLoading: false });
        return null;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to update post';
      set({ error: message, isLoading: false });
      return null;
    }
  },

  deletePost: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.delete(id);
      if (response.success) {
        // Invalidate cache after deleting a post
        get().invalidateCache();
        set({ isLoading: false });
        await get().fetchPosts(undefined, true);
        return true;
      } else {
        set({ error: response.message || 'Failed to delete post', isLoading: false });
        return false;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to delete post';
      set({ error: message, isLoading: false });
      return false;
    }
  },

  publishPost: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.publish(id);
      if (response.success && response.data) {
        // Invalidate cache after publishing a post
        get().invalidateCache();
        set({ currentPost: response.data, isLoading: false });
        return true;
      } else {
        set({ error: response.message || 'Failed to publish post', isLoading: false });
        return false;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to publish post';
      set({ error: message, isLoading: false });
      return false;
    }
  },

  archivePost: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.archive(id);
      if (response.success && response.data) {
        // Invalidate cache after archiving a post
        get().invalidateCache();
        set({ currentPost: response.data, isLoading: false });
        return true;
      } else {
        set({ error: response.message || 'Failed to archive post', isLoading: false });
        return false;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to archive post';
      set({ error: message, isLoading: false });
      return false;
    }
  },

  clearCurrentPost: () => set({ currentPost: null }),
  clearError: () => set({ error: null }),
  invalidateCache: () => set({ cache: {}, postCache: {} }),
}));
