import 'server-only';

/**
 * Server-side API utilities for Next.js Server Components
 * Uses native fetch with Next.js caching for optimal performance
 */

import type {
  ApiResponse,
  BlogPost,
  Category,
  PaginatedResult,
  PaginationParams,
  Tag,
} from '@/types';

import { SERVER_API_URL } from '@/lib/env.server';

const API_BASE_URL = SERVER_API_URL;

/**
 * Build query string from params object
 */
function buildQueryString(params?: Record<string, unknown>): string {
  if (!params) return '';
  
  const searchParams = new URLSearchParams();
  
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      searchParams.append(key, String(value));
    }
  });
  
  const queryString = searchParams.toString();
  return queryString ? `?${queryString}` : '';
}

/**
 * Fetch wrapper with error handling for Server Components
 */
async function serverFetch<T>(
  endpoint: string,
  options?: {
    revalidate?: number | false;
    tags?: string[];
  }
): Promise<T | null> {
  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      next: {
        revalidate: options?.revalidate ?? 60, // Default 60 seconds ISR
        tags: options?.tags,
      },
    });

    if (!response.ok) {
      return null;
    }

    const data: ApiResponse<T> = await response.json();
    return data.data ?? null;
  } catch {
    return null;
  }
}

// ============================================================================
// Posts API
// ============================================================================

export interface FetchPostsParams extends PaginationParams {
  status?: string;
  categoryId?: string;
  tagId?: string;
  search?: string;
  sortBy?: string;
  sortDescending?: boolean;
}

/**
 * Fetch paginated posts with optional filters
 */
export async function fetchPosts(
  params?: FetchPostsParams
): Promise<PaginatedResult<BlogPost> | null> {
  const apiParams = params ? {
    ...params,
    searchTerm: params.search,
    search: undefined,
  } : undefined;
  
  const queryString = buildQueryString(apiParams);
  
  return serverFetch<PaginatedResult<BlogPost>>(`/posts${queryString}`, {
    revalidate: 60, // Revalidate every 60 seconds
    tags: ['posts'],
  });
}

/**
 * Fetch a single post by slug
 */
export async function fetchPostBySlug(slug: string): Promise<BlogPost | null> {
  return serverFetch<BlogPost>(`/posts/slug/${encodeURIComponent(slug)}`, {
    revalidate: 300, // Cache post content for 5 minutes
    tags: ['posts', `post-${slug}`],
  });
}

/**
 * Fetch a single post by ID
 */
export async function fetchPostById(id: string): Promise<BlogPost | null> {
  return serverFetch<BlogPost>(`/posts/${encodeURIComponent(id)}`, {
    revalidate: 300,
    tags: ['posts', `post-${id}`],
  });
}

// ============================================================================
// Categories API
// ============================================================================

/**
 * Fetch all categories
 */
export async function fetchCategories(
  excludeEmptyCategories?: boolean
): Promise<Category[] | null> {
  const queryString = buildQueryString({ excludeEmptyCategories });
  
  return serverFetch<Category[]>(`/categories${queryString}`, {
    revalidate: 300, // Categories change less frequently
    tags: ['categories'],
  });
}

/**
 * Fetch a single category by ID
 */
export async function fetchCategoryById(id: string): Promise<Category | null> {
  return serverFetch<Category>(`/categories/${encodeURIComponent(id)}`, {
    revalidate: 300,
    tags: ['categories', `category-${id}`],
  });
}

// ============================================================================
// Tags API
// ============================================================================

/**
 * Fetch all tags
 */
export async function fetchTags(includeEmpty?: boolean): Promise<Tag[] | null> {
  const queryString = buildQueryString({ includeEmpty });
  
  return serverFetch<Tag[]>(`/tags${queryString}`, {
    revalidate: 300, // Tags change less frequently
    tags: ['tags'],
  });
}

/**
 * Fetch a single tag by ID
 */
export async function fetchTagById(id: string): Promise<Tag | null> {
  return serverFetch<Tag>(`/tags/${encodeURIComponent(id)}`, {
    revalidate: 300,
    tags: ['tags', `tag-${id}`],
  });
}
