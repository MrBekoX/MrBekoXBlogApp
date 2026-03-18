import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { API_BASE_URL } from '@/lib/env';
import type {
  ApiResponse,
  AIAnalysisRequestResponse,
  AiOperationAcceptedResponse,
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
import { createOperationId, withIdempotencyHeader } from '@/lib/idempotency';
import { broadcastAuthMessage } from '@/lib/auth-events';

// CSRF token cache
let csrfToken: string | null = null;
let csrfTokenPromise: Promise<string> | null = null;
type CsrfTokenResponse = ApiResponse<{ token?: string }>;

/**
 * Axios hatasÄ±ndan kullanÄ±cÄ± dostu mesaj Ã§Ä±karÄ±r.
 * Hassas bilgileri (stack trace, internal error details) gizler.
 */
export function getErrorMessage(error: unknown, fallbackMessage = 'Bir hata oluÅŸtu'): string {
  if (!error) return fallbackMessage;

  // Axios error
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<ApiResponse<unknown>>;
    
    // Backend'den gelen hata mesajÄ±
    if (axiosError.response?.data?.message) {
      return axiosError.response.data.message;
    }
    
    // Backend'den gelen errors array
    if (axiosError.response?.data?.errors?.length) {
      return axiosError.response.data.errors[0];
    }

    // HTTP status bazlÄ± generic mesajlar
    switch (axiosError.response?.status) {
      case 400:
        return 'GeÃ§ersiz istek';
      case 401:
        return 'Oturum sÃ¼resi dolmuÅŸ, lÃ¼tfen tekrar giriÅŸ yapÄ±n';
      case 403:
        return 'Bu iÅŸlem iÃ§in yetkiniz yok';
      case 404:
        return 'Ä°stenen kaynak bulunamadÄ±';
      case 429:
        return 'Ã‡ok fazla istek gÃ¶nderdiniz, lÃ¼tfen bekleyin';
      case 500:
      case 502:
      case 503:
        return 'Sunucu hatasÄ±, lÃ¼tfen daha sonra tekrar deneyin';
      default:
        break;
    }

    // Network error
    if (axiosError.code === 'ERR_NETWORK') {
      return 'BaÄŸlantÄ± hatasÄ±, internet baÄŸlantÄ±nÄ±zÄ± kontrol edin';
    }

    // Timeout
    if (axiosError.code === 'ECONNABORTED') {
      return 'Ä°stek zaman aÅŸÄ±mÄ±na uÄŸradÄ±';
    }
  }

  // Standard Error
  if (error instanceof Error) {
    // Hassas bilgileri iÃ§erebilecek mesajlarÄ± filtrele
    const message = error.message.toLowerCase();
    if (message.includes('network') || message.includes('fetch')) {
      return 'BaÄŸlantÄ± hatasÄ±';
    }
    if (message.includes('timeout') || message.includes('aborted')) {
      return 'Ä°stek zaman aÅŸÄ±mÄ±na uÄŸradÄ±';
    }
    // Generic hata mesajÄ± - detay sÄ±zdÄ±rma
    return fallbackMessage;
  }

  return fallbackMessage;
}

/**
 * Clear auth state from sessionStorage to prevent infinite redirect loops.
 * This directly clears the persisted Zustand state without importing the store
 * to avoid circular dependencies (auth-store -> api -> auth-store).
 */
function clearAuthState(): void {
  try {
    // Clear Zustand persisted auth state from sessionStorage
    sessionStorage.removeItem('blogapp-auth');
  } catch {
    // Ignore storage errors
  }
  broadcastAuthMessage({ type: 'logout' });
}

/**
 * Fetches CSRF token from the server.
 * Uses caching to avoid unnecessary requests.
 */
async function fetchCsrfToken(): Promise<string> {
  // Return cached token if available
  if (csrfToken) {
    return csrfToken;
  }

  // If already fetching, wait for the existing promise
  if (csrfTokenPromise) {
    return csrfTokenPromise;
  }

  // Fetch new token
  csrfTokenPromise = (async () => {
    try {
      // Use bare axios to avoid circular interceptor calls
      const response = await axios.get<CsrfTokenResponse>(`${API_BASE_URL}/csrf-token`, {
        withCredentials: true,
      });

      // Cross-origin clients need either an exposed header or a body fallback.
      const token = response.headers['x-csrf-token'] ?? response.data?.data?.token;
      if (token) {
        csrfToken = token;
        return token;
      }

      throw new Error('CSRF token not found in response');
    } catch (error) {
      csrfTokenPromise = null;
      throw error;
    }
  })();

  return csrfTokenPromise;
}

/**
 * Invalidates the cached CSRF token (e.g., on 400 bad request from CSRF validation)
 */
function invalidateCsrfToken(): void {
  csrfToken = null;
  csrfTokenPromise = null;
}

function resolveOperationId(operationId?: string): string {
  return operationId ?? createOperationId();
}

const IDEMPOTENT_NETWORK_RETRY_LIMIT = 2;

function isRetryableNetworkError(error: unknown): boolean {
  if (axios.isAxiosError(error)) {
    if (error.code === 'ERR_CANCELED') {
      return false;
    }

    return error.code === 'ERR_NETWORK'
      || error.code === 'ECONNABORTED'
      || !error.response;
  }

  if (error instanceof Error) {
    const message = error.message.toLowerCase();
    return message.includes('network')
      || message.includes('fetch')
      || message.includes('timeout')
      || message.includes('aborted');
  }

  return false;
}

async function executeWithOperationRetry<T>(
  request: (operationId: string) => Promise<T>,
  operationId?: string,
  maxRetries = IDEMPOTENT_NETWORK_RETRY_LIMIT,
): Promise<T> {
  const resolvedOperationId = resolveOperationId(operationId);

  for (let attempt = 0; ; attempt += 1) {
    try {
      return await request(resolvedOperationId);
    } catch (error) {
      if (attempt >= maxRetries || !isRetryableNetworkError(error)) {
        throw error;
      }
    }
  }
}

export function createAuthMutationConfig(operationId?: string) {
  const resolvedOperationId = resolveOperationId(operationId);
  return {
    operationId: resolvedOperationId,
    config: withIdempotencyHeader(resolvedOperationId),
  };
}

async function executeAuthMutation<TResponse, TBody = null>(
  url: string,
  body: TBody,
  operationId?: string,
): Promise<ApiResponse<TResponse>> {
  return executeWithOperationRetry(async (resolvedOperationId) => {
    const { config } = createAuthMutationConfig(resolvedOperationId);
    const response = await apiClient.post<ApiResponse<TResponse>>(url, body, config);
    return response.data;
  }, operationId);
}

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // Required for HttpOnly cookies
  timeout: 15000, // 15 second timeout
});

// Request interceptor to add CSRF token for state-changing requests
apiClient.interceptors.request.use(
  async (config) => {
    // Only add CSRF token for non-GET requests that modify state
    const method = config.method?.toUpperCase();
    if (method && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      try {
        const token = await fetchCsrfToken();
        config.headers['X-CSRF-TOKEN'] = token;
      } catch {
        // Ignore CSRF token fetch errors - server will return 400 if CSRF is required
      }
    }
    return config;
  },
  (error) => Promise.reject(error)
);

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
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean; _csrfRetry?: boolean };

    // Handle CSRF token errors (400 with antiforgery message)
    if (
      error.response?.status === 400 &&
      originalRequest &&
      !originalRequest._csrfRetry &&
      !originalRequest.url?.includes('/csrf-token')
    ) {
      const errorMessage = (error.response?.data as { message?: string })?.message || '';
      if (errorMessage.toLowerCase().includes('antiforgery') || errorMessage.toLowerCase().includes('csrf')) {
        originalRequest._csrfRetry = true;
        invalidateCsrfToken();

        try {
          const token = await fetchCsrfToken();
          originalRequest.headers['X-CSRF-TOKEN'] = token;
          return apiClient(originalRequest);
        } catch {
          // Retry failed, proceed with normal error handling
        }
      }
    }

    // Only attempt refresh for 401 errors on non-auth endpoints
    if (
      error.response?.status === 401 &&
      originalRequest &&
      !originalRequest._retry &&
      !originalRequest.url?.includes('/auth/login') &&
      !originalRequest.url?.includes('/auth/register') &&
      !originalRequest.url?.includes('/auth/refresh-token') &&
      !originalRequest.url?.includes('/chat/') &&
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
            const response = await authApi.refreshToken();
            if (response.success) {
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
  login: async (data: LoginRequest, operationId?: string): Promise<ApiResponse<AuthResponse>> => {
    return executeAuthMutation<AuthResponse, LoginRequest>('/auth/login', data, operationId);
  },

  register: async (data: RegisterRequest, operationId?: string): Promise<ApiResponse<AuthResponse>> => {
    return executeAuthMutation<AuthResponse, RegisterRequest>('/auth/register', data, operationId);
  },

  logout: async (operationId?: string): Promise<void> => {
    try {
      await executeAuthMutation<object, null>('/auth/logout', null, operationId);
    } catch {
      // Ignore logout errors - cookies will still be cleared locally
    }
  },

  refreshToken: async (operationId?: string): Promise<ApiResponse<AuthResponse>> => {
    return executeAuthMutation<AuthResponse, null>('/auth/refresh-token', null, operationId);
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

  create: async (data: CreatePostRequest, operationId?: string): Promise<ApiResponse<BlogPost>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.post<ApiResponse<BlogPost>>(
        '/posts',
        data,
        withIdempotencyHeader(resolvedOperationId)
      );
      return response.data;
    }, operationId);
  },

  update: async (id: string, data: UpdatePostRequest, operationId?: string): Promise<ApiResponse<BlogPost>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.put<ApiResponse<BlogPost>>(
        `/posts/${id}`,
        data,
        withIdempotencyHeader(resolvedOperationId)
      );
      return response.data;
    }, operationId);
  },

  delete: async (id: string, operationId?: string): Promise<ApiResponse<void>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.delete(`/posts/${id}`, withIdempotencyHeader(resolvedOperationId));
    // 204 No Content baÅŸarÄ±lÄ± bir yanÄ±t
      if (response.status === 204) {
        return { success: true, data: undefined, message: 'Post deleted successfully' };
      }
      return response.data;
    }, operationId);
  },

  publish: async (id: string, operationId?: string): Promise<ApiResponse<BlogPost>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.post<ApiResponse<BlogPost>>(
        `/posts/${id}/publish`,
        null,
        withIdempotencyHeader(resolvedOperationId)
      );
      return response.data;
    }, operationId);
  },

  archive: async (id: string, operationId?: string): Promise<ApiResponse<BlogPost>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.post<ApiResponse<BlogPost>>(
        `/posts/${id}/archive`,
        null,
        withIdempotencyHeader(resolvedOperationId)
      );
      return response.data;
    }, operationId);
  },

  unpublish: async (id: string, operationId?: string): Promise<ApiResponse<BlogPost>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.post<ApiResponse<BlogPost>>(
        `/posts/${id}/unpublish`,
        null,
        withIdempotencyHeader(resolvedOperationId)
      );
      return response.data;
    }, operationId);
  },

  getMyPosts: async (params?: PaginationParams): Promise<ApiResponse<PaginatedResult<BlogPost>>> => {
    const response = await apiClient.get<ApiResponse<PaginatedResult<BlogPost>>>('/posts/my', { params });
    return response.data;
  },

  generateAiSummary: async (id: string, maxSentences?: number, language?: string, operationId?: string): Promise<ApiResponse<AiOperationAcceptedResponse>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const params: { maxSentences?: number; language?: string; operationId: string } = {
        operationId: resolvedOperationId,
      };
      if (maxSentences !== undefined) params.maxSentences = maxSentences;
      if (language !== undefined) params.language = language;

      const response = await apiClient.post<ApiResponse<AiOperationAcceptedResponse>>(
        `/posts/${id}/generate-ai-summary`,
        null,
        withIdempotencyHeader(resolvedOperationId, { params })
      );
      return response.data;
    }, operationId);
  },

  requestAiAnalysis: async (
    id: string,
    data: { language?: string; targetRegion?: string; operationId?: string } = {}
  ): Promise<ApiResponse<AIAnalysisRequestResponse>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.post<ApiResponse<AIAnalysisRequestResponse>>(
        `/posts/${id}/request-ai-analysis`,
        {
          language: data.language,
          targetRegion: data.targetRegion,
          operationId: resolvedOperationId,
        },
        withIdempotencyHeader(resolvedOperationId)
      );
      return response.data;
    }, data.operationId);
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

  create: async (data: CreateCategoryRequest, operationId?: string): Promise<ApiResponse<Category>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.post<ApiResponse<Category>>(
        '/categories',
        data,
        withIdempotencyHeader(resolvedOperationId)
      );
      return response.data;
    }, operationId);
  },

  update: async (id: string, data: CreateCategoryRequest, operationId?: string): Promise<ApiResponse<Category>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.put<ApiResponse<Category>>(
        `/categories/${id}`,
        data,
        withIdempotencyHeader(resolvedOperationId)
      );
      return response.data;
    }, operationId);
  },

  delete: async (id: string, operationId?: string): Promise<ApiResponse<void>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.delete(`/categories/${id}`, withIdempotencyHeader(resolvedOperationId));
      // 204 No Content means success
      if (response.status === 204) {
        return { success: true, data: undefined, message: 'Kategori silindi' };
      }
      return response.data;
    }, operationId);
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

  create: async (data: CreateTagRequest, operationId?: string): Promise<ApiResponse<Tag>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.post<ApiResponse<Tag>>(
        '/tags',
        data,
        withIdempotencyHeader(resolvedOperationId)
      );
      return response.data;
    }, operationId);
  },

  delete: async (id: string, operationId?: string): Promise<ApiResponse<void>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.delete(`/tags/${id}`, withIdempotencyHeader(resolvedOperationId));
      // 204 No Content means success
      if (response.status === 204) {
        return { success: true, data: undefined, message: 'Etiket silindi' };
      }
      return response.data;
    }, operationId);
  },
};

// Comments API
export const commentsApi = {
  getByPostId: async (postId: string): Promise<ApiResponse<Comment[]>> => {
    const response = await apiClient.get<ApiResponse<Comment[]>>(`/posts/${postId}/comments`);
    return response.data;
  },

  create: async (data: CreateCommentRequest, operationId?: string): Promise<ApiResponse<Comment>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.post<ApiResponse<Comment>>(
        '/comments',
        data,
        withIdempotencyHeader(resolvedOperationId)
      );
      return response.data;
    }, operationId);
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

// AI API - Backend uzerinden yonlendiriliyor
export const aiApi = {
  generateTitle: async (content: string, signal?: AbortSignal, operationId?: string): Promise<ApiResponse<AiOperationAcceptedResponse>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.post<ApiResponse<AiOperationAcceptedResponse>>(
        '/ai/generate-title',
        { content, operationId: resolvedOperationId },
        withIdempotencyHeader(resolvedOperationId, { signal })
      );
      return response.data;
    }, operationId);
  },

  generateExcerpt: async (content: string, signal?: AbortSignal, operationId?: string): Promise<ApiResponse<AiOperationAcceptedResponse>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.post<ApiResponse<AiOperationAcceptedResponse>>(
        '/ai/generate-excerpt',
        { content, operationId: resolvedOperationId },
        withIdempotencyHeader(resolvedOperationId, { signal })
      );
      return response.data;
    }, operationId);
  },

  generateTags: async (content: string, signal?: AbortSignal, operationId?: string): Promise<ApiResponse<AiOperationAcceptedResponse>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.post<ApiResponse<AiOperationAcceptedResponse>>(
        '/ai/generate-tags',
        { content, operationId: resolvedOperationId },
        withIdempotencyHeader(resolvedOperationId, { signal })
      );
      return response.data;
    }, operationId);
  },

  generateSeoDescription: async (content: string, signal?: AbortSignal, operationId?: string): Promise<ApiResponse<AiOperationAcceptedResponse>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.post<ApiResponse<AiOperationAcceptedResponse>>(
        '/ai/generate-seo',
        { content, operationId: resolvedOperationId },
        withIdempotencyHeader(resolvedOperationId, { signal })
      );
      return response.data;
    }, operationId);
  },

  improveContent: async (content: string, signal?: AbortSignal, operationId?: string): Promise<ApiResponse<AiOperationAcceptedResponse>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.post<ApiResponse<AiOperationAcceptedResponse>>(
        '/ai/improve-content',
        { content, operationId: resolvedOperationId },
        withIdempotencyHeader(resolvedOperationId, { signal })
      );
      return response.data;
    }, operationId);
  },
};
// Chat API
export const chatApi = {
  sendMessage: async (data: ChatRequest): Promise<ApiResponse<ChatResponse>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const response = await apiClient.post<ApiResponse<ChatResponse>>(
        '/chat/message',
        {
          ...data,
          operationId: resolvedOperationId,
        },
        withIdempotencyHeader(resolvedOperationId)
      );
      return response.data;
    }, data.operationId);
  },
};

// Media API
export const mediaApi = {
  uploadImage: async (
    file: File,
    generateThumbnail = true,
    operationId?: string
  ): Promise<ApiResponse<ImageUploadResult>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const formData = new FormData();
      formData.append('file', file);

      // Note: Set Content-Type to undefined to let axios/browser set it automatically
      // with the correct boundary for multipart/form-data
      const response = await apiClient.post<ApiResponse<ImageUploadResult>>(
        `/media/upload/image?generateThumbnail=${generateThumbnail}`,
        formData,
        withIdempotencyHeader(resolvedOperationId, {
          headers: {
            'Content-Type': undefined,
          },
        })
      );
      return response.data;
    }, operationId);
  },

  uploadImages: async (files: File[], operationId?: string): Promise<ApiResponse<ImageUploadResult[]>> => {
    return executeWithOperationRetry(async (resolvedOperationId) => {
      const formData = new FormData();
      files.forEach((file) => {
        formData.append('files', file);
      });

      // Note: Set Content-Type to undefined to let axios/browser set it automatically
      // with the correct boundary for multipart/form-data
      const response = await apiClient.post<ApiResponse<ImageUploadResult[]>>(
        '/media/upload/images',
        formData,
        withIdempotencyHeader(resolvedOperationId, {
          headers: {
            'Content-Type': undefined,
          },
        })
      );
      return response.data;
    }, operationId);
  },

  deleteImage: async (url: string, operationId?: string): Promise<void> => {
    await executeWithOperationRetry(async (resolvedOperationId) => {
      await apiClient.delete('/media', withIdempotencyHeader(resolvedOperationId, { params: { url } }));
    }, operationId);
  },
};





