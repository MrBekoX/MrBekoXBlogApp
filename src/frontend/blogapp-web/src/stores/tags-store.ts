import { create } from 'zustand';
import { tagsApi } from '@/lib/api';
import type { Tag, CreateTagRequest } from '@/types';

interface TagsState {
  tags: Tag[];
  isLoading: boolean;
  error: string | null;
  cacheVersion: number;
  lastFetched: number | null;

  // Actions
  fetchTags: (forceRefresh?: boolean, includeEmpty?: boolean) => Promise<void>;
  createTag: (data: CreateTagRequest) => Promise<Tag | null>;
  deleteTag: (id: string) => Promise<boolean>;
  invalidateCache: () => void;
}

// Cache duration: 5 minutes
const CACHE_DURATION = 5 * 60 * 1000;

export const useTagsStore = create<TagsState>()((set, get) => ({
  tags: [],
  isLoading: false,
  error: null,
  cacheVersion: 0,
  lastFetched: null,

  fetchTags: async (forceRefresh = false, includeEmpty = false) => {
    const { lastFetched, tags } = get();
    
    // Return cached data if valid and not forcing refresh
    if (!forceRefresh && lastFetched && Date.now() - lastFetched < CACHE_DURATION && tags.length > 0) {
      return;
    }

    set({ isLoading: true, error: null });
    try {
      const response = await tagsApi.getAll(includeEmpty);
      if (response.success && response.data) {
        set({ 
          tags: response.data, 
          isLoading: false, 
          lastFetched: Date.now() 
        });
      } else {
        set({ error: response.message || 'Failed to fetch tags', isLoading: false });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to fetch tags';
      set({ error: message, isLoading: false });
    }
  },

  createTag: async (data: CreateTagRequest) => {
    set({ isLoading: true, error: null });
    try {
      const response = await tagsApi.create(data);
      if (response.success && response.data) {
        // Update local state immediately
        set((state) => ({
          tags: [...state.tags, response.data!],
          isLoading: false,
          cacheVersion: state.cacheVersion + 1,
        }));
        return response.data;
      } else {
        set({ error: response.message || 'Failed to create tag', isLoading: false });
        return null;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to create tag';
      set({ error: message, isLoading: false });
      return null;
    }
  },

  deleteTag: async (id: string) => {
    // Optimistic update
    const previousTags = get().tags;
    set((state) => ({
      tags: state.tags.filter((t) => t.id !== id),
    }));

    try {
      const response = await tagsApi.delete(id);
      if (response.success) {
        set((state) => ({ cacheVersion: state.cacheVersion + 1 }));
        return true;
      } else {
        // Rollback on failure
        set({ tags: previousTags, error: response.message || 'Failed to delete tag' });
        return false;
      }
    } catch (error) {
      // Rollback on error
      const message = error instanceof Error ? error.message : 'Failed to delete tag';
      set({ tags: previousTags, error: message });
      return false;
    }
  },

  invalidateCache: () => {
    set((state) => ({
      cacheVersion: state.cacheVersion + 1,
      lastFetched: null,
    }));
    // Don't auto-fetch here - let components fetch on-demand when they need data
    // This prevents rate limit issues during cache invalidation events
  },
}));

