import { create } from 'zustand';
import { categoriesApi } from '@/lib/api';
import type { Category, CreateCategoryRequest } from '@/types';

interface CategoriesState {
  categories: Category[];
  isLoading: boolean;
  error: string | null;
  cacheVersion: number;
  lastFetched: number | null;

  // Actions
  fetchCategories: (forceRefresh?: boolean, excludeEmptyCategories?: boolean) => Promise<void>;
  createCategory: (data: CreateCategoryRequest) => Promise<Category | null>;
  updateCategory: (id: string, data: CreateCategoryRequest) => Promise<Category | null>;
  deleteCategory: (id: string) => Promise<boolean>;
  invalidateCache: () => void;
}

// Cache duration: 5 minutes
const CACHE_DURATION = 5 * 60 * 1000;

export const useCategoriesStore = create<CategoriesState>()((set, get) => ({
  categories: [],
  isLoading: false,
  error: null,
  cacheVersion: 0,
  lastFetched: null,

  fetchCategories: async (forceRefresh = false, excludeEmptyCategories = true) => {
    const { lastFetched, categories } = get();
    
    // Return cached data if valid and not forcing refresh
    if (!forceRefresh && lastFetched && Date.now() - lastFetched < CACHE_DURATION && categories.length > 0) {
      return;
    }

    set({ isLoading: true, error: null });
    try {
      const response = await categoriesApi.getAll(excludeEmptyCategories);
      if (response.success && response.data) {
        set({ 
          categories: response.data, 
          isLoading: false, 
          lastFetched: Date.now() 
        });
      } else {
        set({ error: response.message || 'Failed to fetch categories', isLoading: false });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to fetch categories';
      set({ error: message, isLoading: false });
    }
  },

  createCategory: async (data: CreateCategoryRequest) => {
    set({ isLoading: true, error: null });
    try {
      const response = await categoriesApi.create(data);
      if (response.success && response.data) {
        // Update local state immediately
        set((state) => ({
          categories: [...state.categories, response.data!],
          isLoading: false,
          cacheVersion: state.cacheVersion + 1,
        }));
        return response.data;
      } else {
        set({ error: response.message || 'Failed to create category', isLoading: false });
        return null;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to create category';
      set({ error: message, isLoading: false });
      return null;
    }
  },

  updateCategory: async (id: string, data: CreateCategoryRequest) => {
    set({ isLoading: true, error: null });
    try {
      const response = await categoriesApi.update(id, data);
      if (response.success && response.data) {
        // Update local state immediately
        set((state) => ({
          categories: state.categories.map((c) => (c.id === id ? response.data! : c)),
          isLoading: false,
          cacheVersion: state.cacheVersion + 1,
        }));
        return response.data;
      } else {
        set({ error: response.message || 'Failed to update category', isLoading: false });
        return null;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to update category';
      set({ error: message, isLoading: false });
      return null;
    }
  },

  deleteCategory: async (id: string) => {
    // Optimistic update
    const previousCategories = get().categories;
    set((state) => ({
      categories: state.categories.filter((c) => c.id !== id),
    }));

    try {
      const response = await categoriesApi.delete(id);
      if (response.success) {
        set((state) => ({ cacheVersion: state.cacheVersion + 1 }));
        // Force refetch to verify deletion was persisted
        await get().fetchCategories(true);
        return true;
      } else {
        // Rollback on failure
        set({ categories: previousCategories, error: response.message || 'Failed to delete category' });
        return false;
      }
    } catch (error) {
      // Rollback on error
      const message = error instanceof Error ? error.message : 'Failed to delete category';
      set({ categories: previousCategories, error: message });
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

