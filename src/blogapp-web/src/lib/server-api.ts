import 'server-only';

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

async function serverFetch<T>(
  endpoint: string,
  options?: {
    revalidate?: number | false;
    tags?: string[];
  }
): Promise<T | null> {
  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, options?.revalidate === false
      ? { cache: 'no-store' }
      : {
          next: {
            revalidate: options?.revalidate ?? 60,
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

export interface FetchPostsParams extends PaginationParams {
  status?: string;
  categoryId?: string;
  tagId?: string;
  search?: string;
  sortBy?: string;
  sortDescending?: boolean;
}

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
    revalidate: 60,
    tags: ['posts'],
  });
}

export async function fetchPostBySlug(slug: string): Promise<BlogPost | null> {
  return serverFetch<BlogPost>(`/posts/slug/${encodeURIComponent(slug)}`, {
    revalidate: 300,
    tags: ['posts', `post-${slug}`],
  });
}

export async function fetchPostById(id: string): Promise<BlogPost | null> {
  return serverFetch<BlogPost>(`/posts/${encodeURIComponent(id)}`, {
    revalidate: 300,
    tags: ['posts', `post-${id}`],
  });
}

export async function fetchCategories(
  excludeEmptyCategories?: boolean
): Promise<Category[] | null> {
  const queryString = buildQueryString({ excludeEmptyCategories });

  return serverFetch<Category[]>(`/categories${queryString}`, {
    revalidate: 300,
    tags: ['categories'],
  });
}

export async function fetchCategoryById(id: string): Promise<Category | null> {
  return serverFetch<Category>(`/categories/${encodeURIComponent(id)}`, {
    revalidate: 300,
    tags: ['categories', `category-${id}`],
  });
}

export async function fetchTags(includeEmpty?: boolean): Promise<Tag[] | null> {
  const queryString = buildQueryString({ includeEmpty });

  return serverFetch<Tag[]>(`/tags${queryString}`, {
    revalidate: 300,
    tags: ['tags'],
  });
}

export async function fetchTagById(id: string): Promise<Tag | null> {
  return serverFetch<Tag>(`/tags/${encodeURIComponent(id)}`, {
    revalidate: 300,
    tags: ['tags', `tag-${id}`],
  });
}
