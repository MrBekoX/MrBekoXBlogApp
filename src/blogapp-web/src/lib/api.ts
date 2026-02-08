import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { API_BASE_URL } from '@/lib/env';
import type {
  ApiResponse,
  AISummaryResponse,
  AuthResponse,
  BlogPost,
  Category,
  ChatRequest,
  ChatResponse,
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

// Auth storage key used by Zustand persist middleware
const AUTH_STORAGE_KEY = 'auth-storage';

/**
 * Axios hatasından kullanıcı dostu mesaj çıkarır.
 * Hassas bilgileri (stack trace, internal error details) gizler.
 */
export function getErrorMessage(error: unknown, fallbackMessage = 'Bir hata oluştu'): string {
  if (!error) return fallbackMessage;

  // Axios error
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<ApiResponse<unknown>>;
    
    // Backend'den gelen hata mesajı
    if (axiosError.response?.data?.message) {
      return axiosError.response.data.message;
    }
    
    // Backend'den gelen errors array
    if (axiosError.response?.data?.errors?.length) {
      return axiosError.response.data.errors[0];
    }

    // HTTP status bazlı generic mesajlar
    switch (axiosError.response?.status) {
      case 400:
        return 'Geçersiz istek';
      case 401:
        return 'Oturum süresi dolmuş, lütfen tekrar giriş yapın';
      case 403:
        return 'Bu işlem için yetkiniz yok';
      case 404:
        return 'İstenen kaynak bulunamadı';
      case 429:
        return 'Çok fazla istek gönderdiniz, lütfen bekleyin';
      case 500:
      case 502:
      case 503:
        return 'Sunucu hatası, lütfen daha sonra tekrar deneyin';
      default:
        break;
    }

    // Network error
    if (axiosError.code === 'ERR_NETWORK') {
      return 'Bağlantı hatası, internet bağlantınızı kontrol edin';
    }

    // Timeout
    if (axiosError.code === 'ECONNABORTED') {
      return 'İstek zaman aşımına uğradı';
    }
  }

  // Standard Error
  if (error instanceof Error) {
    // Hassas bilgileri içerebilecek mesajları filtrele
    const message = error.message.toLowerCase();
    if (message.includes('network') || message.includes('fetch')) {
      return 'Bağlantı hatası';
    }
    if (message.includes('timeout') || message.includes('aborted')) {
      return 'İstek zaman aşımına uğradı';
    }
    // Generic hata mesajı - detay sızdırma
    return fallbackMessage;
  }

  return fallbackMessage;
}

/**
 * Clear auth state from localStorage to prevent infinite redirect loops.
 * This directly updates the persisted Zustand state without importing the store
 * to avoid circular dependencies (auth-store -> api -> auth-store).
 */
function clearAuthState(): void {
  try {
    const stored = localStorage.getItem(AUTH_STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      parsed.state = {
        ...parsed.state,
        user: null,
        authStatus: 'unauthenticated',
      };
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(parsed));
    }
  } catch {
    // If parsing fails, just remove the entire storage
    localStorage.removeItem(AUTH_STORAGE_KEY);
  }
}

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // Required for HttpOnly cookies
  timeout: 15000, // 15 second timeout
});

// No request interceptor needed - cookies are sent automatically with withCredentials: true

// Response interceptor for handling token refresh
// Global flags to prevent infinite redirect loops
let isRefreshing = false;
let refreshPromise: Promise<boolean> | null = null;
let isRedirecting = false;
let lastRedirectTime = 0;
const REDIRECT_COOLDOWN = 10000; // 10 seconds cooldown between redirects

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
      !originalRequest.url?.includes('/auth/register') &&
      !originalRequest.url?.includes('/auth/refresh-token') &&
      !isRedirecting
    ) {
      originalRequest._retry = true;

      // If already refreshing, wait for the existing refresh to complete
      if (isRefreshing && refreshPromise) {
        try {
          const success = await refreshPromise;
          if (success) {
            return apiClient(originalRequest);
          }
        } catch {
          // Refresh failed, will redirect below
        }
      } else {
        // Start new refresh attempt
        isRefreshing = true;
        refreshPromise = (async () => {
          try {
            const response = await apiClient.post<ApiResponse<AuthResponse>>('/auth/refresh-token');
            if (response.data.success) {
              return true;
            }
            return false;
          } catch {
            return false;
          } finally {
            isRefreshing = false;
            refreshPromise = null;
          }
        })();

        try {
          const success = await refreshPromise;
          if (success) {
            return apiClient(originalRequest);
          }
        } catch {
          // Refresh failed
        }
      }

      // Refresh failed - clear auth state and redirect to login (with cooldown protection)
      const now = Date.now();
      const timeSinceLastRedirect = now - lastRedirectTime;

      if (!isRedirecting && typeof window !== 'undefined' && timeSinceLastRedirect > REDIRECT_COOLDOWN) {
        isRedirecting = true;
        lastRedirectTime = now;

        // CRITICAL: Clear auth state BEFORE redirect to prevent infinite loop
        // Without this, localStorage keeps 'authenticated' status and login page
        // redirects back to dashboard, creating an infinite loop
        clearAuthState();

        // Use replace to prevent going back to protected page
        window.location.replace('/mrbekox-console');

        // Reset after cooldown to allow for future redirects
        setTimeout(() => { isRedirecting = false; }, REDIRECT_COOLDOWN);
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
  getAll: async (params?: PaginationParams & { status?: string; categoryId?: string; tagId?: string; search?: string; sortBy?: string; sortDescending?: boolean }): Promise<ApiResponse<PaginatedResult<BlogPost>>> => {
    // Map 'search' to 'searchTerm' for backend compatibility
    const apiParams = params ? {
      ...params,
      searchTerm: params.search,
      search: undefined,
    } : undefined;
    const response = await apiClient.get<ApiResponse<PaginatedResult<BlogPost>>>('/posts', { params: apiParams });
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

  generateAiSummary: async (id: string, maxSentences?: number, language?: string): Promise<ApiResponse<AISummaryResponse>> => {
    const params: { maxSentences?: number; language?: string } = {};
    if (maxSentences !== undefined) params.maxSentences = maxSentences;
    if (language !== undefined) params.language = language;

    const response = await apiClient.post<ApiResponse<AISummaryResponse>>(
      `/posts/${id}/generate-ai-summary`,
      null,
      { params }
    );
    return response.data;
  },
};

// Categories API
export const categoriesApi = {
  getAll: async (excludeEmptyCategories?: boolean): Promise<ApiResponse<Category[]>> => {
    const params = excludeEmptyCategories !== undefined ? { excludeEmptyCategories } : {};
    const response = await apiClient.get<ApiResponse<Category[]>>('/categories', { params });
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
    const response = await apiClient.delete(`/categories/${id}`);
    // 204 No Content means success
    if (response.status === 204) {
      return { success: true, data: undefined, message: 'Kategori silindi' };
    }
    return response.data;
  },
};

// Tags API
export const tagsApi = {
  getAll: async (includeEmpty?: boolean): Promise<ApiResponse<Tag[]>> => {
    const params = includeEmpty !== undefined ? { includeEmpty } : {};
    const response = await apiClient.get<ApiResponse<Tag[]>>('/tags', { params });
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
    const response = await apiClient.delete(`/tags/${id}`);
    // 204 No Content means success
    if (response.status === 204) {
      return { success: true, data: undefined, message: 'Etiket silindi' };
    }
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

// AI API - Backend üzerinden yönlendiriliyor
export const aiApi = {
  generateTitle: async (content: string, signal?: AbortSignal): Promise<{ title: string }> => {
    const response = await apiClient.post<{ title: string }>(
      '/ai/generate-title',
      { content },
      { signal }
    );
    return response.data;
  },

  generateExcerpt: async (content: string, signal?: AbortSignal): Promise<{ excerpt: string }> => {
    const response = await apiClient.post<{ excerpt: string }>(
      '/ai/generate-excerpt',
      { content },
      { signal }
    );
    return response.data;
  },

  generateTags: async (content: string, signal?: AbortSignal): Promise<{ tags: string[] }> => {
    const response = await apiClient.post<{ tags: string[] }>(
      '/ai/generate-tags',
      { content },
      { signal }
    );
    return response.data;
  },

  generateSeoDescription: async (content: string, signal?: AbortSignal): Promise<{ description: string }> => {
    const response = await apiClient.post<{ description: string }>(
      '/ai/generate-seo',
      { content },
      { signal }
    );
    return response.data;
  },

  improveContent: async (content: string, signal?: AbortSignal): Promise<{ content: string }> => {
    const response = await apiClient.post<{ content: string }>(
      '/ai/improve-content',
      { content },
      { signal }
    );
    return response.data;
  },
};

// Chat API
export const chatApi = {
  sendMessage: async (data: ChatRequest): Promise<ApiResponse<ChatResponse>> => {
    const response = await apiClient.post<ApiResponse<ChatResponse>>('/chat/message', data);
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
