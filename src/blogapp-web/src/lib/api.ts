import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import type {
  ApiResponse,
  AuthResponse,
  BlogPost,
  Category,
  Comment,
  CreateCategoryRequest,
  CreateCommentRequest,
  CreatePostRequest,
  CreateTagRequest,
  ImageUploadResult,
  LoginRequest,
  PaginatedResult,
  PaginationParams,
  RegisterRequest,
  Tag,
  UpdatePostRequest,
} from '@/types';

// API Base URL - Production'da NEXT_PUBLIC_API_URL environment variable kullanılmalı
// Örnek: NEXT_PUBLIC_API_URL=https://api.yourdomain.com/api/v1
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5116/api/v1';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // Required for HttpOnly cookies
});

// No request interceptor needed - cookies are sent automatically with withCredentials: true

// Response interceptor for handling token refresh
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    // Only attempt refresh for 401 errors on non-auth endpoints
    if (
      error.response?.status === 401 &&
      originalRequest &&
      !originalRequest._retry &&
      !originalRequest.url?.includes('/auth/login') &&
      !originalRequest.url?.includes('/auth/register')
    ) {
      originalRequest._retry = true;

      try {
        // Refresh endpoint reads token from HttpOnly cookie automatically
        const response = await apiClient.post<ApiResponse<AuthResponse>>('/auth/refresh-token');

        if (response.data.success) {
          // New cookies are set automatically by the server response
          // Retry the original request
          return apiClient(originalRequest);
        }
      } catch {
        // Refresh failed - redirect to login
        if (typeof window !== 'undefined') {
          window.location.href = '/login';
        }
      }
    }

    return Promise.reject(error);
  }
);

// Auth API - Uses HttpOnly cookies (no localStorage)
export const authApi = {
  login: async (data: LoginRequest): Promise<ApiResponse<AuthResponse>> => {
    // Cookies are set automatically by the server response
    const response = await apiClient.post<ApiResponse<AuthResponse>>('/auth/login', data);
    return response.data;
  },

  register: async (data: RegisterRequest): Promise<ApiResponse<AuthResponse>> => {
    // Cookies are set automatically by the server response
    const response = await apiClient.post<ApiResponse<AuthResponse>>('/auth/register', data);
    return response.data;
  },

  logout: async (): Promise<void> => {
    // Server clears HttpOnly cookies
    try {
      await apiClient.post('/auth/logout');
    } catch {
      // Ignore logout errors - cookies will be cleared by server
    }
  },

  refreshToken: async (): Promise<ApiResponse<AuthResponse>> => {
    // Server reads refresh token from HttpOnly cookie
    const response = await apiClient.post<ApiResponse<AuthResponse>>('/auth/refresh-token');
    return response.data;
  },

  getCurrentUser: async (): Promise<ApiResponse<AuthResponse['user']>> => {
    const response = await apiClient.get<ApiResponse<AuthResponse['user']>>('/auth/me');
    return response.data;
  },
};

// Posts API
export const postsApi = {
  getAll: async (params?: PaginationParams & { status?: string; categoryId?: string; tagId?: string; search?: string }): Promise<ApiResponse<PaginatedResult<BlogPost>>> => {
    const response = await apiClient.get<ApiResponse<PaginatedResult<BlogPost>>>('/posts', { params });
    return response.data;
  },

  getById: async (id: string): Promise<ApiResponse<BlogPost>> => {
    const response = await apiClient.get<ApiResponse<BlogPost>>(`/posts/${id}`);
    return response.data;
  },

  getBySlug: async (slug: string): Promise<ApiResponse<BlogPost>> => {
    const response = await apiClient.get<ApiResponse<BlogPost>>(`/posts/slug/${slug}`);
    return response.data;
  },

  create: async (data: CreatePostRequest): Promise<ApiResponse<BlogPost>> => {
    const response = await apiClient.post<ApiResponse<BlogPost>>('/posts', data);
    return response.data;
  },

  update: async (id: string, data: UpdatePostRequest): Promise<ApiResponse<BlogPost>> => {
    const response = await apiClient.put<ApiResponse<BlogPost>>(`/posts/${id}`, data);
    return response.data;
  },

  delete: async (id: string): Promise<ApiResponse<void>> => {
    const response = await apiClient.delete(`/posts/${id}`);
    // 204 No Content başarılı bir yanıt
    if (response.status === 204) {
      return { success: true, message: 'Post deleted successfully' };
    }
    return response.data;
  },

  publish: async (id: string): Promise<ApiResponse<BlogPost>> => {
    const response = await apiClient.post<ApiResponse<BlogPost>>(`/posts/${id}/publish`);
    return response.data;
  },

  archive: async (id: string): Promise<ApiResponse<BlogPost>> => {
    const response = await apiClient.post<ApiResponse<BlogPost>>(`/posts/${id}/archive`);
    return response.data;
  },

  unpublish: async (id: string): Promise<ApiResponse<BlogPost>> => {
    const response = await apiClient.post<ApiResponse<BlogPost>>(`/posts/${id}/unpublish`);
    return response.data;
  },

  getMyPosts: async (params?: PaginationParams): Promise<ApiResponse<PaginatedResult<BlogPost>>> => {
    const response = await apiClient.get<ApiResponse<PaginatedResult<BlogPost>>>('/posts/my', { params });
    return response.data;
  },
};

// Categories API
export const categoriesApi = {
  getAll: async (): Promise<ApiResponse<Category[]>> => {
    const response = await apiClient.get<ApiResponse<Category[]>>('/categories');
    return response.data;
  },

  getById: async (id: string): Promise<ApiResponse<Category>> => {
    const response = await apiClient.get<ApiResponse<Category>>(`/categories/${id}`);
    return response.data;
  },

  create: async (data: CreateCategoryRequest): Promise<ApiResponse<Category>> => {
    const response = await apiClient.post<ApiResponse<Category>>('/categories', data);
    return response.data;
  },

  update: async (id: string, data: CreateCategoryRequest): Promise<ApiResponse<Category>> => {
    const response = await apiClient.put<ApiResponse<Category>>(`/categories/${id}`, data);
    return response.data;
  },

  delete: async (id: string): Promise<ApiResponse<void>> => {
    const response = await apiClient.delete<ApiResponse<void>>(`/categories/${id}`);
    return response.data;
  },
};

// Tags API
export const tagsApi = {
  getAll: async (): Promise<ApiResponse<Tag[]>> => {
    const response = await apiClient.get<ApiResponse<Tag[]>>('/tags');
    return response.data;
  },

  getById: async (id: string): Promise<ApiResponse<Tag>> => {
    const response = await apiClient.get<ApiResponse<Tag>>(`/tags/${id}`);
    return response.data;
  },

  create: async (data: CreateTagRequest): Promise<ApiResponse<Tag>> => {
    const response = await apiClient.post<ApiResponse<Tag>>('/tags', data);
    return response.data;
  },

  delete: async (id: string): Promise<ApiResponse<void>> => {
    const response = await apiClient.delete<ApiResponse<void>>(`/tags/${id}`);
    return response.data;
  },
};

// Comments API
export const commentsApi = {
  getByPostId: async (postId: string): Promise<ApiResponse<Comment[]>> => {
    const response = await apiClient.get<ApiResponse<Comment[]>>(`/posts/${postId}/comments`);
    return response.data;
  },

  create: async (data: CreateCommentRequest): Promise<ApiResponse<Comment>> => {
    const response = await apiClient.post<ApiResponse<Comment>>('/comments', data);
    return response.data;
  },

  approve: async (id: string): Promise<ApiResponse<void>> => {
    const response = await apiClient.post<ApiResponse<void>>(`/comments/${id}/approve`);
    return response.data;
  },

  delete: async (id: string): Promise<ApiResponse<void>> => {
    const response = await apiClient.delete<ApiResponse<void>>(`/comments/${id}`);
    return response.data;
  },
};

// AI API
const AI_API_URL = process.env.NEXT_PUBLIC_AI_API_URL || 'http://localhost:8000';

export const aiApi = {
  generateTitle: async (content: string): Promise<{ title: string }> => {
    const response = await axios.post<{ title: string }>(`${AI_API_URL}/ai/generate-title`, { content });
    return response.data;
  },

  generateExcerpt: async (content: string): Promise<{ excerpt: string }> => {
    const response = await axios.post<{ excerpt: string }>(`${AI_API_URL}/ai/generate-excerpt`, { content });
    return response.data;
  },

  generateTags: async (content: string): Promise<{ tags: string[] }> => {
    const response = await axios.post<{ tags: string[] }>(`${AI_API_URL}/ai/generate-tags`, { content });
    return response.data;
  },

  generateSeoDescription: async (content: string): Promise<{ description: string }> => {
    const response = await axios.post<{ description: string }>(`${AI_API_URL}/ai/generate-seo`, { content });
    return response.data;
  },

  improveContent: async (content: string): Promise<{ content: string }> => {
    const response = await axios.post<{ content: string }>(`${AI_API_URL}/ai/improve-content`, { content });
    return response.data;
  },
};

// Media API
export const mediaApi = {
  uploadImage: async (
    file: File,
    generateThumbnail = true
  ): Promise<ApiResponse<ImageUploadResult>> => {
    const formData = new FormData();
    formData.append('file', file);

    const response = await apiClient.post<ApiResponse<ImageUploadResult>>(
      `/media/upload/image?generateThumbnail=${generateThumbnail}`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );
    return response.data;
  },

  uploadImages: async (files: File[]): Promise<ApiResponse<ImageUploadResult[]>> => {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append('files', file);
    });

    const response = await apiClient.post<ApiResponse<ImageUploadResult[]>>(
      '/media/upload/images',
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );
    return response.data;
  },

  deleteImage: async (url: string): Promise<void> => {
    await apiClient.delete('/media', { params: { url } });
  },
};
