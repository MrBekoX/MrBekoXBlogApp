import { create } from 'zustand';
import type { BlogPost, CreatePostRequest, PaginatedResult, UpdatePostRequest } from '@/types';
import { postsApi } from '@/lib/api';

interface PostsState {
  posts: PaginatedResult<BlogPost> | null;
  currentPost: BlogPost | null;
  isLoading: boolean;
  error: string | null;

  fetchPosts: (params?: {
    pageNumber?: number;
    pageSize?: number;
    status?: string;
    categoryId?: string;
    tagId?: string;
    search?: string;
  }) => Promise<void>;
  fetchPostById: (id: string) => Promise<void>;
  fetchPostBySlug: (slug: string) => Promise<void>;
  createPost: (data: CreatePostRequest) => Promise<BlogPost | null>;
  updatePost: (id: string, data: UpdatePostRequest) => Promise<BlogPost | null>;
  deletePost: (id: string) => Promise<boolean>;
  publishPost: (id: string) => Promise<boolean>;
  archivePost: (id: string) => Promise<boolean>;
  clearCurrentPost: () => void;
  clearError: () => void;
}

export const usePostsStore = create<PostsState>()((set, get) => ({
  posts: null,
  currentPost: null,
  isLoading: false,
  error: null,

  fetchPosts: async (params) => {
    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.getAll(params);
      if (response.success && response.data) {
        set({ posts: response.data, isLoading: false });
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

  fetchPostBySlug: async (slug: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.getBySlug(slug);
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

  createPost: async (data: CreatePostRequest) => {
    console.log('Creating post with data:', data);
    set({ isLoading: true, error: null });
    try {
      const response = await postsApi.create(data);
      console.log('Create post response:', response);
      if (response.success && response.data) {
        set({ isLoading: false });
        await get().fetchPosts();
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
        set({ isLoading: false });
        await get().fetchPosts();
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
}));
